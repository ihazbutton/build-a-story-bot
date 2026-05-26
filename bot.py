import os
import json
import random
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RARE_WORDS = [
    ("petrichor", "the pleasant smell of rain on dry earth"),
    ("ephemeral", "lasting for a very short time"),
    ("sonder", "the realisation that each passerby has a life as vivid and complex as one's own"),
    ("hiraeth", "a homesickness for a home you can't return to, or that never was"),
    ("vellichor", "the strange wistfulness of used bookshops"),
    ("limerence", "the state of being infatuated or obsessed with another person"),
    ("nemophilist", "one who loves the forest and its beauty"),
    ("solivagant", "a person who wanders alone"),
    ("querencia", "a place from which one's strength is drawn"),
    ("selcouth", "unfamiliar and rare, yet marvellous"),
    ("psithurism", "the sound of the wind through trees"),
    ("eunoia", "beautiful thinking; a well-mind"),
    ("halcyon", "idyllically calm and peaceful"),
    ("sempiternal", "eternal and unchanging; everlasting"),
    ("mellifluous", "sweet or musical; pleasant to hear"),
    ("phosphene", "the light and colours seen when pressing on closed eyelids"),
    ("apricity", "the warmth of the sun in winter"),
    ("fernweh", "a craving for travel; an ache for distant places"),
    ("crepuscular", "relating to twilight"),
    ("ineffable", "too great or extreme to be expressed in words"),
    ("numinous", "having a strong spiritual quality; seeming to suggest the presence of a god"),
    ("susurrus", "a whispering or murmuring sound"),
    ("tenebrous", "dark, shadowy, and obscure"),
    ("scintilla", "a tiny trace or spark of a specified quality"),
    ("palimpsest", "something bearing visible traces of an earlier form"),
    ("diaphanous", "light, delicate, and translucent"),
    ("sillage", "the scent that lingers in the air after someone has passed"),
    ("yugen", "a profound awareness of the universe that triggers emotional responses too deep for words"),
    ("toska", "a longing with nothing to long for; a vague restlessness"),
    ("meraki", "to do something with soul, creativity, and love"),
    ("quiddity", "the inherent nature or essence of someone or something"),
    ("noctilucent", "shining or glowing in the night"),
    ("lethologica", "the inability to remember the right word"),
    ("oblivescence", "the process of forgetting"),
    ("kenopsia", "the eerie, desolate atmosphere of a place that is usually busy but is now empty"),
    ("chrysalism", "the amniotic tranquility of being indoors during a thunderstorm"),
    ("rubatosis", "the unsettling awareness of your own heartbeat"),
    ("onism", "the frustration of being stuck in just one body that inhabits only one place at a time"),
    ("altschmerz", "weariness with the same old issues that you've always had"),
    ("vemödalen", "the frustration of photographing something amazing when thousands of similar photos exist"),
]

# In-memory game state per chat: {chat_id: game_dict}
games = {}


def get_game(chat_id):
    return games.get(chat_id)


async def judge_sentence(word: str, definition: str, sentence: str, story_so_far: list) -> tuple[bool, str]:
    story_context = "\n".join(story_so_far) if story_so_far else "(This is the opening sentence of the story.)"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f'You are judging a collaborative story-building game.\n\n'
                f'The rare word for this turn is: "{word}" — meaning: {definition}\n\n'
                f'Story so far:\n{story_context}\n\n'
                f'Player\'s sentence: "{sentence}"\n\n'
                f'Judge whether the word "{word}" appears AND is used correctly (matches its definition) AND naturally (not forced). '
                f'Respond ONLY in this exact JSON format with no extra text:\n'
                f'{{"pass": true, "feedback": "one short encouraging sentence"}}\n'
                f'or\n'
                f'{{"pass": false, "feedback": "one short hint about what went wrong"}}'
            )
        }]
    )

    try:
        result = json.loads(message.content[0].text.strip())
        return bool(result["pass"]), str(result["feedback"])
    except Exception:
        word_present = word.lower() in sentence.lower()
        return word_present, "Nice use of the word!" if word_present else f'The word "{word}" wasn\'t found in your sentence.'


async def announce_turn(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = games[chat_id]
    player_id = game["players"][game["current_player_idx"]]
    player_name = game["player_names"][player_id]

    total_turns = game["rounds_per_player"] * len(game["players"])
    turn_num = game["turns_completed"] + 1

    available = [w for w in RARE_WORDS if w[0] not in game["used_words"]]
    if not available:
        game["used_words"] = []
        available = RARE_WORDS

    word, definition = random.choice(available)
    game["current_word"] = word
    game["current_definition"] = definition
    game["used_words"].append(word)

    story_preview = ""
    if game["story"]:
        recent = game["story"][-3:]
        label = f"last 3 of {len(game['story'])} sentences" if len(game["story"]) > 3 else "so far"
        story_preview = f"\n\n📜 *Story {label}:*\n" + "\n".join(f"_{s}_" for s in recent)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✏️ *{player_name}'s turn!* (Turn {turn_num}/{total_turns})\n\n"
            f"Your rare word: *{word}*\n"
            f"_{definition}_"
            f"{story_preview}\n\n"
            f"Add one sentence to the story using *{word}* naturally!"
        ),
        parse_mode="Markdown",
    )


async def newgame_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id in games and games[chat_id]["status"] not in ("ended",):
        await update.message.reply_text("A game is already running! Use /endgame to end it first.")
        return

    games[chat_id] = {
        "status": "waiting",
        "players": [],
        "player_names": {},
        "current_player_idx": 0,
        "current_word": None,
        "current_definition": None,
        "story": [],
        "used_words": [],
        "rounds_per_player": 3,
        "turns_completed": 0,
    }

    await update.message.reply_text(
        "📖 *Build-a-Story!*\n\n"
        "A new game is starting! Players, use /join to get in.\n"
        "Once everyone has joined, use /begin to start.\n\n"
        "*How to play:* Each turn you get a rare word and its definition. "
        "Add one sentence to our shared story using that word naturally — "
        "an AI judge decides if you pulled it off! ✨",
        parse_mode="Markdown",
    )


async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = get_game(chat_id)

    if not game or game["status"] == "ended":
        await update.message.reply_text("No game waiting to start. Use /newgame to create one!")
        return

    if game["status"] != "waiting":
        await update.message.reply_text("Game already in progress! Wait for the next one.")
        return

    if user.id in game["players"]:
        await update.message.reply_text("You're already in!")
        return

    game["players"].append(user.id)
    game["player_names"][user.id] = user.first_name
    count = len(game["players"])

    await update.message.reply_text(
        f"✅ *{user.first_name}* joined! ({count} player{'s' if count != 1 else ''} so far)\n"
        + ("Ready! Use /begin when everyone's in." if count >= 1 else "Waiting for more players..."),
        parse_mode="Markdown",
    )


async def begin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    if not game or game["status"] == "ended":
        await update.message.reply_text("No game to start. Use /newgame first!")
        return
    if game["status"] != "waiting":
        await update.message.reply_text("Game already started!")
        return
    if len(game["players"]) < 1:
        await update.message.reply_text("Need at least 1 player to begin!")
        return

    game["status"] = "playing"
    names = ", ".join(game["player_names"].values())
    total = game["rounds_per_player"] * len(game["players"])
    await update.message.reply_text(
        f"🚀 *Game on!* Players: {names}\n_{total} turns total — {game['rounds_per_player']} per player_",
        parse_mode="Markdown",
    )
    await announce_turn(context, chat_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = get_game(chat_id)

    if not game or game["status"] != "playing":
        return

    current_player_id = game["players"][game["current_player_idx"]]
    if user.id != current_player_id:
        return

    sentence = update.message.text.strip()
    word = game["current_word"]
    definition = game["current_definition"]

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    passed, feedback = await judge_sentence(word, definition, sentence, game["story"])

    if passed:
        game["story"].append(sentence)
        game["turns_completed"] += 1
        total_turns = game["rounds_per_player"] * len(game["players"])

        await update.message.reply_text(
            f'✅ *Great use of "{word}"!*\n_{feedback}_',
            parse_mode="Markdown",
        )

        if game["turns_completed"] >= total_turns:
            await finish_game(context, chat_id)
        else:
            game["current_player_idx"] = (game["current_player_idx"] + 1) % len(game["players"])
            await announce_turn(context, chat_id)
    else:
        await update.message.reply_text(
            f'❌ *Not quite!* _{feedback}_\n\nTry again — use *{word}* naturally in your sentence.',
            parse_mode="Markdown",
        )


async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = games[chat_id]
    game["status"] = "ended"

    full_story = "\n\n".join(f"{i + 1}. {s}" for i, s in enumerate(game["story"]))
    players = ", ".join(game["player_names"].values())

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎉 *The story is complete!*\n\n"
            f"📖 *Our Story:*\n\n{full_story}\n\n"
            f"_Built by: {players}_\n\n"
            f"Play again with /newgame!"
        ),
        parse_mode="Markdown",
    )


async def story_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    if not game or not game["story"]:
        await update.message.reply_text("No story yet! Start a game with /newgame.")
        return

    full_story = "\n\n".join(f"{i + 1}. {s}" for i, s in enumerate(game["story"]))
    await update.message.reply_text(f"📖 *Story so far:*\n\n{full_story}", parse_mode="Markdown")


async def endgame_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    if not game or game["status"] == "ended":
        await update.message.reply_text("No active game to end.")
        return

    await finish_game(context, chat_id)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Build-a-Story Bot*\n\n"
        "*Commands:*\n"
        "/newgame — Start a new game\n"
        "/join — Join the current game\n"
        "/begin — Begin once everyone has joined\n"
        "/story — See the full story so far\n"
        "/endgame — End the game early\n\n"
        "*How to play:*\n"
        "Best played in a group chat! Each turn you get a rare word with its definition. "
        "Add one sentence to the shared story using that word naturally. "
        "An AI judge decides if you pulled it off. "
        "After everyone has taken 3 turns the full story is revealed. 🎉",
        parse_mode="Markdown",
    )


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("newgame", newgame_command))
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("begin", begin_command))
    app.add_handler(CommandHandler("story", story_command))
    app.add_handler(CommandHandler("endgame", endgame_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Build-a-Story bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
