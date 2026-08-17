from firestore_db import FieldFilter, transactional as firestore_transactional
from firestore_db import MockFirestoreClient
from datetime import datetime, timezone
from typing import Dict, Optional
import asyncio
import math


def finite_amount(value) -> Optional[float]:
    """Return value as a finite float, or None if it's not a valid finite number."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount):
        return None
    return amount


class UserManager:
    def __init__(self, db):
        self.db = db
        self.users_ref = db.collection('users')

    def _get_or_create_user_sync(self, user_id: int, first_name: str, username: str) -> Dict:
        user_doc = self.users_ref.document(str(user_id)).get()
        if user_doc.exists:
            return user_doc.to_dict()
        user_data = {
            'user_id': user_id,
            'first_name': first_name,
            'username': username or '',
            'balance': 0,
            'play_wallet': 0,
            'bonus': 0,
            'phone': '',
            'registered': False,
            'total_games': 0,
            'wins': 0,
            'losses': 0,
            'is_playing': False,
            'active_round_id': None,
            'awaiting_screenshot': False,
            'referred_by': None,
            'created_at': datetime.now(tz=timezone.utc),
            'updated_at': datetime.now(tz=timezone.utc),
        }
        self.users_ref.document(str(user_id)).set(user_data)
        return user_data

    async def get_or_create_user(self, user_id: int, first_name: str, username: str) -> Dict:
        return await asyncio.to_thread(self._get_or_create_user_sync, user_id, first_name, username)

    def _get_user_sync(self, user_id: int) -> Optional[Dict]:
        user_doc = self.users_ref.document(str(user_id)).get()
        return user_doc.to_dict() if user_doc.exists else None

    async def get_user(self, user_id: int) -> Optional[Dict]:
        return await asyncio.to_thread(self._get_user_sync, user_id)

    async def user_exists(self, user_id: int) -> bool:
        return await asyncio.to_thread(
            lambda: self.users_ref.document(str(user_id)).get().exists
        )

    async def update_balance(self, user_id: int, amount: float) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        new_balance = user.get('play_wallet', 0) + amount
        if new_balance < 0:
            return False
        self.users_ref.document(str(user_id)).update({
            'play_wallet': new_balance,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return True

    async def deduct_balance(self, user_id: int, amount: float) -> bool:
        user = await self.get_user(user_id)
        if not user or user.get('play_wallet', 0) < amount:
            return False
        self.users_ref.document(str(user_id)).update({
            'play_wallet': user['play_wallet'] - amount,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return True

    async def transfer_to_play_wallet(self, user_id: int, amount: float) -> bool:
        user = await self.get_user(user_id)
        if not user or user.get('play_wallet', 0) < amount:
            return False
        self.users_ref.document(str(user_id)).update({
            'play_wallet': user.get('play_wallet', 0) + amount,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return True

    async def add_winnings(self, user_id: int, amount: float) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        self.users_ref.document(str(user_id)).update({
            'play_wallet': user.get('play_wallet', 0) + amount,
            'wins': user.get('wins', 0) + 1,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return True

    async def update_game_stats(self, user_id: int, won: bool) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        update_data = {
            'total_games': user.get('total_games', 0) + 1,
            'updated_at': datetime.now(tz=timezone.utc),
        }
        if won:
            update_data['wins'] = user.get('wins', 0) + 1
        else:
            update_data['losses'] = user.get('losses', 0) + 1
        self.users_ref.document(str(user_id)).update(update_data)
        return True

    async def set_playing_status(self, user_id: int, is_playing: bool) -> bool:
        update = {
            'is_playing': is_playing,
            'updated_at': datetime.now(tz=timezone.utc),
        }
        if not is_playing:
            update['active_round_id'] = None
        self.users_ref.document(str(user_id)).update(update)
        return True

    async def validate_withdrawal(self, user_id: int, amount: float) -> dict:
        """Validate a withdrawal request. Returns {'ok': True} or {'ok': False, 'error': str}."""
        try:
            from datetime import timedelta
            from handlers.bot_content import get_config_value
            import traceback

            amount = finite_amount(amount)
            if amount is None or amount <= 0:
                return {'ok': False, 'error': 'invalid_amount'}

            # Read live config from Firestore (admin-editable via Config tab)
            min_withdraw = get_config_value('cfg_min_withdraw', self.db, as_type=int)
            max_withdraw = get_config_value('cfg_max_withdraw', self.db, as_type=int)
            min_initial_deposit = get_config_value('cfg_min_initial_deposit', self.db, as_type=int)
            max_per_day = get_config_value('cfg_max_withdraw_per_day', self.db, as_type=int)
            cooldown_hours = get_config_value('cfg_withdraw_cooldown_hours', self.db, as_type=int)

            user = await self.get_user(user_id)
            if not user:
                return {'ok': False, 'error': 'not_registered'}

            if not user.get('phone'):
                return {'ok': False, 'error': 'no_phone'}

            bal = float(user.get('play_wallet', 0))
            if float(amount) < min_withdraw:
                return {'ok': False, 'error': 'below_min', 'min': min_withdraw, 'balance': bal}
            if float(amount) > bal:
                return {'ok': False, 'error': 'insufficient', 'balance': bal}
            if float(amount) > max_withdraw:
                return {'ok': False, 'error': 'above_max', 'max': max_withdraw}

            created = user.get('created_at')
            if created:
                # Firestore sometimes returns created as ISO string if we mock it, or timestamp.
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    except Exception:
                        pass
                if isinstance(created, datetime):
                    if not created.tzinfo:
                        created = created.replace(tzinfo=timezone.utc)
                    account_age = datetime.now(tz=timezone.utc) - created
                    if account_age < timedelta(days=1):
                        return {'ok': False, 'error': 'account_new'}

            try:
                approved_deposits = list(self.db.collection('deposits').where('userId', '==', str(user_id)).where('status', '==', 'approved').get())
                total_deposited = sum(float(d.to_dict().get('amount', 0)) for d in approved_deposits)
                if total_deposited < min_initial_deposit:
                    return {'ok': False, 'error': 'deposit_required', 'min_deposit': min_initial_deposit, 'current_deposit': total_deposited}
            except Exception as e:
                import logging; logging.getLogger(__name__).error(f"Error checking deposits: {e}")

            try:
                pending = list(self.db.collection('withdrawals').where('userId', '==', str(user_id)).where('status', '==', 'pending').limit(1).get())
                if pending:
                    return {'ok': False, 'error': 'pending_exists'}
            except Exception as e:
                import logging; logging.getLogger(__name__).error(f"Error checking pending withdrawals: {e}")

            try:
                today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                today_docs = list(self.db.collection('withdrawals').where('userId', '==', str(user_id)).get())
                today_count = 0
                for d in today_docs:
                    dd = d.to_dict()
                    if dd.get('status') in ('pending', 'approved'):
                        created_at = dd.get('createdAt')
                        if isinstance(created_at, str):
                            try:
                                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            except Exception:
                                pass
                        if isinstance(created_at, datetime):
                            if not created_at.tzinfo:
                                created_at = created_at.replace(tzinfo=timezone.utc)
                            if created_at >= today_start:
                                today_count += 1
                if today_count >= max_per_day:
                    return {'ok': False, 'error': 'daily_limit', 'limit': max_per_day}
            except Exception as e:
                import logging; logging.getLogger(__name__).error(f"Error checking daily limit: {e}")

            try:
                recent_docs = list(self.db.collection('withdrawals').where('userId', '==', str(user_id)).get())
                if recent_docs:
                    # Filter and sort safely
                    valid_docs = []
                    for doc in recent_docs:
                        d = doc.to_dict()
                        t = d.get('processedAt') or d.get('createdAt')
                        if isinstance(t, str):
                            try:
                                t = datetime.fromisoformat(t.replace('Z', '+00:00'))
                            except Exception:
                                t = datetime.min.replace(tzinfo=timezone.utc)
                        if getattr(t, 'tzinfo', None) is None and isinstance(t, datetime):
                            t = t.replace(tzinfo=timezone.utc)
                        valid_docs.append((t, d))

                    valid_docs.sort(key=lambda x: x[0], reverse=True)
                    if valid_docs:
                        last_time, last = valid_docs[0]
                        if isinstance(last_time, datetime):
                            cooldown_end = last_time + timedelta(hours=cooldown_hours)
                            if datetime.now(tz=timezone.utc) < cooldown_end:
                                remaining = (cooldown_end - datetime.now(tz=timezone.utc)).total_seconds() / 60
                                return {'ok': False, 'error': 'cooldown', 'minutes': int(remaining), 'hours': cooldown_hours}
            except Exception as e:
                import logging; logging.getLogger(__name__).error(f"Error checking cooldown: {e}")

            return {'ok': True}
        except Exception as e:
            import logging; logging.getLogger(__name__).error(f"CRITICAL ERROR in validate_withdrawal: {e}\n{traceback.format_exc()}")
            return {'ok': False, 'error': 'system_error'}

    async def get_user_history(self, user_id: int, limit: int = 10) -> list:
        """Get recent completed rounds the user participated in."""
        uid_str = str(user_id)
        try:
            rounds = self.db.collection('rounds').where('status', '==', 'completed').get()
            user_rounds = []
            for doc in rounds:
                rd = doc.to_dict()
                players = rd.get('players', {})
                if uid_str in players:
                    rd['id'] = doc.id
                    user_rounds.append(rd)
            # Sort by completed_at descending
            user_rounds.sort(
                key=lambda r: r.get('completed_at', r.get('created_at', '')),
                reverse=True,
            )
            return user_rounds[:limit]
        except Exception:
            return []

    async def get_all_users(self, limit: int = 100) -> list:
        users = self.users_ref.limit(limit).get()
        return [user.to_dict() for user in users]

    async def get_leaderboard(self, limit: int = 10) -> list:
        users = self.users_ref.order_by('wins', 'DESCENDING').limit(limit).get()
        return [user.to_dict() for user in users]

    async def register_user(self, user_id: int, name: str, phone: str, telebirr_name: str = '') -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        import settlement
        result = settlement.register_user(
            self.db,
            user_id,
            name,
            phone,
            telebirr_name,
            idempotency_key=f"registration:{user_id}:{phone}",
        )
        return bool(result.get("ok"))

    async def is_registered(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        return bool(user.get('registered')) and bool(user.get('phone'))

    async def get_balance_info(self, user_id: int) -> Optional[Dict]:
        user = await self.get_user(user_id)
        if not user:
            return None
        pw = user.get('play_wallet', 0)
        if isinstance(pw, dict) and ('__type' in pw or '_type' in pw):
            pw = float(pw.get('value', 0))
        else:
            try:
                pw = float(pw or 0)
            except Exception:
                pw = 0.0

        bonus = user.get('bonus', 0)
        if isinstance(bonus, dict) and ('__type' in bonus or '_type' in bonus):
            bonus = float(bonus.get('value', 0))
        else:
            try:
                bonus = float(bonus or 0)
            except Exception:
                bonus = 0.0

        return {
            'balance': pw,
            'play_wallet': pw,
            'bonus': bonus,
            'first_name': user.get('first_name', ''),
        }

    async def transfer_funds(self, sender_id: int, recipient_id: int, amount: float, idempotency_key: str = None) -> bool:
        amount = finite_amount(amount)
        if amount is None or amount <= 0 or sender_id == recipient_id:
            return False
        import settlement
        result = settlement.transfer_funds(
            self.db,
            sender_id,
            recipient_id,
            amount,
            idempotency_key=idempotency_key,
        )
        return bool(result.get("ok"))

    async def convert_bonus(self, user_id: int, rate: int = 10, idempotency_key: str = None) -> Optional[float]:
        user = await self.get_user(user_id)
        if not user:
            return None
        rate = finite_amount(rate)
        if rate is None or rate <= 0:
            return None
        import settlement
        result = settlement.convert_bonus(
            self.db,
            user_id,
            rate,
            idempotency_key=idempotency_key,
        )
        return result.get("etb") if result.get("ok") else None

    async def set_referred_by(self, new_user_id: int, referrer_id: int) -> bool:
        """Attribute a referrer to a user, but only once (never overwrite)."""
        user = await self.get_user(new_user_id)
        if not user or user.get('referred_by'):
            return False
        self.users_ref.document(str(new_user_id)).update({
            'referred_by': referrer_id,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return True

    async def count_referral(self, new_user_id: int) -> Optional[int]:
        """
        Record a completed referral when the invited user registers — once.

        Only increments the referrer's invited-friends count. No bonus/ETB is
        awarded. Returns the referrer's id if this was a new referral, else None.
        """
        user = await self.get_user(new_user_id)
        if not user:
            return None
        referrer_id = user.get('referred_by')
        if not referrer_id or user.get('referral_credited'):
            return None
        referrer = await self.get_user(referrer_id)
        if not referrer:
            return None

        self.users_ref.document(str(referrer_id)).update({
            'referrals': referrer.get('referrals', 0) + 1,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        self.users_ref.document(str(new_user_id)).update({
            'referral_credited': True,
            'updated_at': datetime.now(tz=timezone.utc),
        })
        return referrer_id

    async def get_referral_count(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user.get('referrals', 0)) if user else 0

    async def set_awaiting_screenshot(self, user_id: int, awaiting: bool) -> None:
        self.users_ref.document(str(user_id)).update({
            'awaiting_screenshot': awaiting,
            'updated_at': datetime.now(tz=timezone.utc),
        })
