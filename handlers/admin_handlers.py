import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler

class AdminHandlers:
    def __init__(self, db, game_engine, prediction):
        self.db = db
        self.game_engine = game_engine
        self.prediction = prediction
        admin_id = os.getenv("ADMIN_CHAT_ID", "")
        self.admin_users = [int(admin_id)] if admin_id else []

    def get_handler(self):
        """Return conversation handler for admin"""
        return ConversationHandler(
            entry_points=[CommandHandler('admin', self.admin_panel)],
            states={},
            fallbacks=[]
        )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin control panel"""
        if update.effective_user.id not in self.admin_users:
            await update.message.reply_text("⛔ Unauthorized. This bot is for admins only.")
            return

        keyboard = [
            [InlineKeyboardButton("📊 Dashboard", callback_data="admin_dashboard")],
            [InlineKeyboardButton("🎮 Manage Games", callback_data="admin_games")],
            [InlineKeyboardButton("👥 Players", callback_data="admin_players")],
            [InlineKeyboardButton("🧠 Prediction Control", callback_data="admin_prediction")],
            [InlineKeyboardButton("📈 Reports", callback_data="admin_reports")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🔧 *Admin Control Panel*\n\nSelect an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin dashboard"""
        query = update.callback_query
        await query.answer()

        stats = self.game_engine.get_stats()
        users = self.db.collection('users').get()

        total_users = len(list(users))
        total_balance = sum(user.to_dict().get('play_wallet', 0) for user in self.db.collection('users').get())

        text = f"""📊 *Admin Dashboard*

👥 *Users:* {total_users}
💰 *Total Balance:* {total_balance:.2f} ETB
🎮 *Active Games:* {stats['active_players']}
🏆 *Games Played:* {stats['games_played']}
⭐ *Winners Today:* {stats['winners_today']}"""

        await query.edit_message_text(text, parse_mode='Markdown')

    async def prediction_control(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prediction algorithm control"""
        query = update.callback_query
        await query.answer()

        keyboard = [
            [InlineKeyboardButton("🎯 Enable Admin Win", callback_data="admin_win_enable")],
            [InlineKeyboardButton("🚫 Disable Admin Win", callback_data="admin_win_disable")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """🧠 *Prediction Algorithm Control*

Current Mode: *Automatic*
Admin Override: *Disabled*

Select action: """

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    async def select_player_for_win(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select player for guaranteed win"""
        query = update.callback_query
        await query.answer()

        users = self.db.collection('users').where('is_playing', '==', True).get()

        keyboard = []
        for user in users[:10]:
            user_data = user.to_dict()
            keyboard.append([InlineKeyboardButton(
                f"{user_data.get('first_name', 'Unknown')} (Balance: {user_data.get('play_wallet', 0)} ETB)",
                callback_data=f"admin_select_{user.id}"
            )])

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_prediction")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = "🎯 *Select Player for Guaranteed Win*\n\nLow-balance players prioritized:"

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
