"""Idempotent deposit and withdrawal settlement shared by bot processes."""

from datetime import datetime, timedelta, timezone
import math
import uuid

import firestore_db


def _already_processed(data):
    return {
        "ok": False,
        "error": "already_processed",
        "status": data.get("status"),
    }


def _settlement_result(data, user_id, amount, status):
    return {
        "ok": True,
        "user_id": user_id,
        "amount": amount,
        "status": status,
        "first_name": data.get("firstName", "?"),
    }


def _active_round_ids(user_data):
    """Normalize new multi-stake state and the legacy single-round pointer."""
    values = user_data.get("active_round_ids") if isinstance(user_data, dict) else None
    ids = []
    if isinstance(values, (list, tuple, set)):
        ids.extend(str(value) for value in values if value not in (None, ""))
    legacy = user_data.get("active_round_id") if isinstance(user_data, dict) else None
    if legacy not in (None, "") and str(legacy) not in ids:
        ids.append(str(legacy))
    return list(dict.fromkeys(ids))


def _active_round_state(active_ids):
    ids = list(dict.fromkeys(str(value) for value in (active_ids or []) if value not in (None, "")))
    return {
        "active_round_ids": ids,
        "is_playing": bool(ids),
        "active_round_id": ids[-1] if ids else None,
    }


def create_deposit(db, deposit_data):
    """Create one pending deposit per payment transaction ID."""
    if hasattr(db, "create_deposit"):
        return db.create_deposit(deposit_data)
    transaction_id = str(deposit_data.get("transactionId", "")).strip()
    if len(transaction_id) < 3:
        return {"ok": False, "error": "invalid_transaction_id"}
    amount = float(deposit_data.get("amount", 0) or 0)
    if not math.isfinite(amount) or amount < 10:
        return {"ok": False, "error": "invalid_amount"}

    def _apply(transaction):
        query = db.collection("deposits").where("transactionId", "==", transaction_id).limit(1)
        transaction.query(query)
        existing = list(query.get())
        if existing:
            return {
                "ok": False,
                "error": "duplicate_txn",
                "deposit_id": existing[0].id,
            }
        ref = db.collection("deposits").document()
        transaction.set(ref, {
            **deposit_data,
            "amount": amount,
            "status": "pending",
        })
        return {
            "ok": True,
            "deposit_id": ref.id,
            "status": "pending",
            "amount": amount,
            "transaction_id": transaction_id,
        }

    return firestore_db.run_idempotent(
        f"deposit-create:{transaction_id}",
        "deposit_create",
        _apply,
    )


def transfer_funds(db, sender_id, recipient_id, amount, idempotency_key=None):
    """Move play-wallet value between two users exactly once."""
    if hasattr(db, "transfer_funds"):
        return db.transfer_funds(sender_id, recipient_id, amount, idempotency_key)
    sender_id = str(sender_id)
    recipient_id = str(recipient_id)
    amount = float(amount)
    if sender_id == recipient_id or not math.isfinite(amount) or amount <= 0:
        return {"ok": False, "error": "invalid_transfer"}
    request_key = str(idempotency_key or uuid.uuid4())

    def _apply(transaction):
        sender_ref = db.collection("users").document(sender_id)
        recipient_ref = db.collection("users").document(recipient_id)
        sender_doc = transaction.get(sender_ref)
        recipient_doc = transaction.get(recipient_ref)
        if not sender_doc.exists or not recipient_doc.exists:
            return {"ok": False, "error": "user_not_found"}
        sender = sender_doc.to_dict()
        recipient = recipient_doc.to_dict()
        sender_wallet = float(sender.get("play_wallet", 0) or 0)
        if sender_wallet < amount:
            return {"ok": False, "error": "insufficient"}
        now = datetime.now(tz=timezone.utc)
        transaction.update(sender_ref, {"play_wallet": sender_wallet - amount, "updated_at": now})
        transaction.update(recipient_ref, {
            "play_wallet": float(recipient.get("play_wallet", 0) or 0) + amount,
            "updated_at": now,
        })
        return {"ok": True, "amount": amount, "sender_id": sender_id, "recipient_id": recipient_id}

    return firestore_db.run_idempotent(
        f"transfer:{request_key}",
        "wallet_transfer",
        _apply,
        lock_keys=[f"user:{sender_id}", f"user:{recipient_id}"],
    )


def convert_bonus(db, user_id, rate=10, idempotency_key=None):
    """Convert bonus coins into play-wallet value exactly once."""
    if hasattr(db, "convert_bonus"):
        return db.convert_bonus(user_id, rate, idempotency_key)
    user_id = str(user_id)
    rate = float(rate)
    if not math.isfinite(rate) or rate <= 0:
        return {"ok": False, "error": "invalid_rate"}
    request_key = str(idempotency_key or uuid.uuid4())

    def _apply(transaction):
        user_ref = db.collection("users").document(user_id)
        user_doc = transaction.get(user_ref)
        if not user_doc.exists:
            return {"ok": False, "error": "user_not_found"}
        user = user_doc.to_dict()
        coins = float(user.get("bonus", 0) or 0)
        if coins <= 0:
            return {"ok": False, "error": "no_bonus"}
        etb = coins / rate
        transaction.update(user_ref, {
            "bonus": 0,
            "play_wallet": float(user.get("play_wallet", 0) or 0) + etb,
            "updated_at": datetime.now(tz=timezone.utc),
        })
        return {"ok": True, "etb": etb, "user_id": user_id}

    return firestore_db.run_idempotent(
        f"bonus-convert:{request_key}",
        "bonus_conversion",
        _apply,
        lock_key=f"user:{user_id}",
    )


def register_user(db, user_id, name, phone, telebirr_name="", idempotency_key=None):
    """Register a user and award the welcome bonus at most once."""
    if hasattr(db, "register_user"):
        return db.register_user(user_id, name, phone, telebirr_name, idempotency_key)
    user_id = str(user_id)
    request_key = str(idempotency_key or uuid.uuid4())

    def _apply(transaction):
        user_ref = db.collection("users").document(user_id)
        user_doc = transaction.get(user_ref)
        if not user_doc.exists:
            return {"ok": False, "error": "user_not_found"}
        user = user_doc.to_dict()
        already_registered = bool(user.get("registered")) and bool(user.get("phone"))
        wallet = float(user.get("play_wallet", 0) or 0)
        if not already_registered:
            wallet += 10
        transaction.update(user_ref, {
            "first_name": name,
            "phone": phone,
            "telebirr_name": telebirr_name,
            "registered": True,
            "play_wallet": wallet,
            "updated_at": datetime.now(tz=timezone.utc),
        })
        return {"ok": True, "welcome_bonus": 10 if not already_registered else 0}

    return firestore_db.run_idempotent(
        f"register:{user_id}:{request_key}",
        "user_registration",
        _apply,
        lock_key=f"user:{user_id}",
    )


def commit_round_number(
    db,
    round_id,
    expected_count,
    number,
    game_target=None,
    target_winner=None,
):
    """Append one called number exactly once for a round."""
    round_id = str(round_id)
    expected_count = int(expected_count)
    number = int(number)

    def _apply(transaction):
        round_ref = db.collection("rounds").document(round_id)
        round_doc = transaction.get(round_ref)
        if not round_doc.exists:
            return {"number": None, "error": "Round not found"}
        data = round_doc.to_dict()
        if data.get("status") != "playing":
            return {"number": None, "error": "Round is not playing"}
        called = list(data.get("called_numbers", []) or [])
        if len(called) != expected_count:
            return {
                "number": called[-1] if len(called) > expected_count else None,
                "stale": True,
            }
        if number in called:
            return {"number": called[-1] if called else None, "stale": True}
        called.append(number)
        updates = {
            "called_numbers": called,
            "last_called_number": number,
            "last_called_at": datetime.now(tz=timezone.utc),
        }
        if data.get("game_started_at") is not None:
            updates["next_number_at"] = _next_number_at(data.get("game_started_at"), len(called))
        if data.get("game_target") != game_target and game_target is not None:
            updates["game_target"] = int(game_target)
        if target_winner is not None and not data.get("target_winner"):
            updates["target_winner"] = target_winner
        transaction.update(round_ref, updates)
        return {"number": number}

    return firestore_db.run_idempotent(
        f"round-call:{round_id}:{expected_count}",
        "round_number_call",
        _apply,
        lock_key=f"round:{round_id}",
    )


def _next_number_at(started_at, call_count):
    """Compute a future next-number deadline without publishing 0s/1s."""
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    minimum_deadline = now + timedelta(seconds=5)
    if isinstance(started_at, str):
        try:
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return minimum_deadline
    if started_at is None or not hasattr(started_at, "__add__"):
        return minimum_deadline
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    anchored_deadline = started_at + timedelta(seconds=5 * (int(call_count) + 1))
    return max(anchored_deadline, minimum_deadline)


def join_round(
    db,
    round_id,
    user_id,
    cartela_numbers,
    user_name="Player",
    max_cartelas=2,
    total_cartelas=75,
    idempotency_key=None,
    require_pending=False,
    pending_revision=0,
):
    """Join a round and reserve cards with one durable account/round transaction."""
    round_id = str(round_id)
    user_id = int(user_id)
    uid_str = str(user_id)
    try:
        selected = [int(number) for number in cartela_numbers]
    except (TypeError, ValueError):
        return {"error": "Invalid cartela selection"}
    if len(selected) > int(max_cartelas):
        return {"error": f"Maximum {max_cartelas} cartelas allowed"}
    if not selected:
        return {"error": "Must select at least 1 cartela"}
    if any(number < 1 or number > int(total_cartelas) for number in selected):
        return {"error": "Invalid cartela number"}
    if len(selected) != len(set(selected)):
        return {"error": "Duplicate cartela numbers in selection"}
    request_key = str(idempotency_key or uuid.uuid4())

    def _apply(transaction):
        round_ref = db.collection("rounds").document(round_id)
        round_doc = transaction.get(round_ref)
        if not round_doc.exists:
            return {"error": "Round not found"}
        round_data = round_doc.to_dict()
        status = round_data.get("status")
        called = round_data.get("called_numbers", []) or []
        players = round_data.get("players", {}) or {}
        existing_player = players.get(uid_str) if isinstance(players.get(uid_str), dict) else {}
        existing_cartelas = []
        for value in existing_player.get("cartelas", []) if existing_player else []:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= int(total_cartelas) and number not in existing_cartelas:
                existing_cartelas.append(number)
        combined_cartelas = list(dict.fromkeys(existing_cartelas + selected))
        if len(combined_cartelas) > int(max_cartelas):
            return {"error": f"Maximum {max_cartelas} cartelas allowed"}
        added_cartelas = [number for number in combined_cartelas if number not in existing_cartelas]

        if require_pending:
            current_revision = int(round_data.get("pending_revision", 0) or 0)
            # Revisions are round-global: another player may select or release a
            # card after this player’s last response. Only reject an impossible
            # rollback; membership in this player’s current pending set remains
            # the authoritative join check.
            if int(pending_revision or 0) and current_revision < int(pending_revision):
                return {"error": "Cartela selection changed; please review your selected cartelas"}
            pending = round_data.get("pending_selections", {}) or {}
            pending_numbers = pending.get(uid_str, []) if isinstance(pending, dict) else []
            try:
                allowed_pending = {int(number) for number in pending_numbers}
            except (TypeError, ValueError):
                allowed_pending = set()
            if not set(added_cartelas).issubset(allowed_pending):
                return {"error": "Cartela selection was cancelled before round finalization"}

        if status == "playing":
            pending = round_data.get("pending_selections", {}) or {}
            allowed = pending.get(uid_str, []) if isinstance(pending, dict) else []
            try:
                allowed_numbers = {int(number) for number in allowed}
            except (TypeError, ValueError):
                allowed_numbers = set()
            started_at = round_data.get("game_started_at")
            if isinstance(started_at, str):
                try:
                    started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                except ValueError:
                    started_at = None
            if isinstance(started_at, datetime) and started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            grace_ended = not isinstance(started_at, datetime) or datetime.now(tz=timezone.utc) > started_at + timedelta(seconds=5)
            if called or grace_ended or not set(added_cartelas).issubset(allowed_numbers):
                return {"error": "Round is no longer accepting players"}
        elif status != "selecting":
            return {"error": "Round is no longer accepting players"}

        taken = set(round_data.get("taken_cartelas", []) or [])
        for number in added_cartelas:
            if number in taken:
                return {"error": f"Cartela #{number} is already taken"}

        try:
            round_stake = float(round_data.get("stake", 10) or 0)
        except (TypeError, ValueError):
            return {"error": "Invalid round stake"}
        if not math.isfinite(round_stake) or round_stake < 0:
            return {"error": "Invalid round stake"}
        raw_reservations = round_data.get("pending_reservations", {}) or {}
        reservation_numbers = raw_reservations.get(uid_str, []) if isinstance(raw_reservations, dict) else []
        try:
            reserved_cartelas = {int(number) for number in reservation_numbers}
        except (TypeError, ValueError):
            reserved_cartelas = set()
        newly_chargeable = [number for number in added_cartelas if number not in reserved_cartelas]
        total_cost = round_stake * len(newly_chargeable)
        user_ref = db.collection("users").document(uid_str)
        user_doc = transaction.get(user_ref)
        if not user_doc.exists:
            now = datetime.now(tz=timezone.utc)
            user_data = {
                "user_id": user_id,
                "first_name": user_name or "Player",
                "username": "",
                "balance": 0,
                "play_wallet": 0.0,
                "bonus": 0,
                "phone": "",
                "registered": False,
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "is_playing": False,
                "active_round_id": None,
                "active_round_ids": [],
                "created_at": now,
                "updated_at": now,
            }
            transaction.set(user_ref, user_data)
        else:
            user_data = user_doc.to_dict()

        active_round_ids = _active_round_ids(user_data)
        try:
            wallet = float(user_data.get("play_wallet", 0) or 0)
        except (TypeError, ValueError):
            wallet = 0.0
        if not math.isfinite(wallet) or wallet < total_cost:
            return {
                "error": f"Not enough balance. Need {total_cost} ETB, have {wallet} ETB"
            }

        now = datetime.now(tz=timezone.utc)
        if round_id not in active_round_ids:
            active_round_ids.append(round_id)
        transaction.update(user_ref, {
            "play_wallet": round(wallet - total_cost, 2),
            **_active_round_state(active_round_ids),
            "updated_at": now,
        })
        player_entry = {
            "cartelas": combined_cartelas,
            "name": existing_player.get("name") or user_name,
            "joined_at": existing_player.get("joined_at") or now.isoformat(),
        }
        updated_taken = list(round_data.get("taken_cartelas", []) or [])
        updated_taken.extend(number for number in added_cartelas if number not in updated_taken)
        round_updates = {
            f"players.{uid_str}": player_entry,
            "player_count": int(round_data.get("player_count", 0) or 0) + len(added_cartelas),
            "taken_cartelas": updated_taken,
        }
        if status == "playing":
            round_updates["derash"] = (int(round_data.get("player_count", 0) or 0) + len(added_cartelas)) * round_stake * 0.80
        if isinstance(round_data.get("pending_selections"), dict):
            pending = dict(round_data.get("pending_selections") or {})
            pending[uid_str] = [number for number in pending.get(uid_str, []) if str(number).isdigit() and int(number) not in added_cartelas]
            round_updates["pending_selections"] = pending
        if isinstance(raw_reservations, dict):
            reservations = dict(raw_reservations)
            reservations[uid_str] = [number for number in reservation_numbers if str(number).isdigit() and int(number) not in added_cartelas]
            round_updates["pending_reservations"] = reservations
        transaction.update(round_ref, round_updates)
        return {
            "status": "expanded" if existing_cartelas and added_cartelas else "joined",
            "cost": total_cost,
            "reserved_cost": round_stake * len([number for number in added_cartelas if number in reserved_cartelas]),
            "cartelas": combined_cartelas,
            "player_count": int(round_data.get("player_count", 0) or 0) + len(added_cartelas),
        }

    return firestore_db.run_idempotent(
        f"round-join:{request_key}",
        "round_join",
        _apply,
        lock_keys=[f"round:{round_id}", f"user:{uid_str}"],
    )


def refund_no_winner(db, round_id, players=None, stake=0, idempotency_key=None):
    """Refund a no-winner round exactly once and finalize it atomically."""
    round_id = str(round_id)
    request_key = str(idempotency_key or f"round-refund:{round_id}")
    try:
        fallback_stake = float(stake or 0)
    except (TypeError, ValueError):
        fallback_stake = 0.0
    if not math.isfinite(fallback_stake) or fallback_stake < 0:
        return {"ok": False, "error": "invalid_stake"}

    requested_players = players or {}
    lock_keys = [f"round:{round_id}"] + [
        f"user:{uid}" for uid in requested_players.keys()
    ]

    def _apply(transaction):
        round_ref = db.collection("rounds").document(round_id)
        round_doc = transaction.get(round_ref)
        if not round_doc.exists:
            return {"ok": False, "error": "round_not_found", "round_id": round_id}
        round_data = round_doc.to_dict()
        if round_data.get("payout_processed") or round_data.get("refunded"):
            return {
                "ok": True,
                "status": "already_finalized",
                "round_id": round_id,
                "refunded": False,
                "amount": 0.0,
            }
        if round_data.get("status") == "completed" and round_data.get("winners"):
            return {
                "ok": False,
                "error": "winner_round_requires_payout",
                "round_id": round_id,
            }
        authoritative_players = round_data.get("players") or requested_players
        try:
            round_stake = float(round_data.get("stake", fallback_stake) or 0)
        except (TypeError, ValueError):
            round_stake = fallback_stake
        if not math.isfinite(round_stake) or round_stake < 0:
            return {"ok": False, "error": "invalid_stake", "round_id": round_id}

        now = datetime.now(tz=timezone.utc)
        total = 0.0
        for uid_str, player_info in authoritative_players.items():
            cartelas = (player_info or {}).get("cartelas") or []
            refund = round_stake * len(cartelas)
            if refund <= 0:
                continue
            user_ref = db.collection("users").document(str(uid_str))
            user_doc = transaction.get(user_ref)
            if not user_doc.exists:
                continue
            user_data = user_doc.to_dict()
            active_round_ids = [active_id for active_id in _active_round_ids(user_data) if active_id != round_id]
            update = {
                "play_wallet": float(user_data.get("play_wallet", 0) or 0) + refund,
                "total_games": int(user_data.get("total_games", 0) or 0) + 1,
                "losses": int(user_data.get("losses", 0) or 0) + 1,
                **_active_round_state(active_round_ids),
                "updated_at": now,
            }
            transaction.update(user_ref, update)
            total += refund

        transaction.update(round_ref, {
            "status": "completed",
            "winners": [],
            "winner_name": "No winner",
            "prize_per_winner": 0,
            "admin_profit": 0,
            "refunded": True,
            "payout_processed": True,
            "completed_at": now,
        })
        return {
            "ok": True,
            "status": "completed",
            "round_id": round_id,
            "refunded": True,
            "amount": total,
        }

    return firestore_db.run_idempotent(
        f"round-refund:{request_key}",
        "round_no_winner_refund",
        _apply,
        lock_keys=lock_keys,
    )


def create_withdrawal(db, withdrawal_data, idempotency_key=None):
    """Create and debit one withdrawal atomically on the authoritative backend."""
    if hasattr(db, "create_withdrawal"):
        return db.create_withdrawal(withdrawal_data, idempotency_key)
    user_id = str(withdrawal_data.get("userId", ""))
    amount = float(withdrawal_data.get("amount", 0) or 0)
    if not user_id:
        return {"ok": False, "error": "invalid_user"}
    if not math.isfinite(amount) or amount <= 0:
        return {"ok": False, "error": "invalid_amount"}
    request_key = str(idempotency_key or withdrawal_data.get("idempotencyKey") or uuid.uuid4())

    def _apply(transaction):
        pending_query = db.collection("withdrawals").where("userId", "==", user_id).where("status", "==", "pending")
        transaction.query(pending_query)
        if list(pending_query.get()):
            return {"ok": False, "error": "pending_exists"}

        user_ref = db.collection("users").document(user_id)
        user_doc = transaction.get(user_ref)
        if not user_doc.exists:
            return {"ok": False, "error": "user_not_found"}
        user_data = user_doc.to_dict()
        current_wallet = float(user_data.get("play_wallet", 0) or 0)
        if current_wallet < amount:
            return {"ok": False, "error": "insufficient"}

        withdrawal_ref = db.collection("withdrawals").document()
        transaction.update(user_ref, {
            "play_wallet": firestore_db.Increment(-amount),
            "updated_at": datetime.now(tz=timezone.utc),
        })
        transaction.set(withdrawal_ref, {
            **withdrawal_data,
            "userId": user_id,
            "amount": amount,
            "status": "pending",
            "createdAt": withdrawal_data.get("createdAt") or datetime.now(tz=timezone.utc),
            "processedAt": None,
        })
        return {
            "ok": True,
            "withdrawal_id": withdrawal_ref.id,
            "status": "pending",
            "amount": amount,
            "phone": withdrawal_data.get("phone", ""),
            "user_id": user_id,
        }

    return firestore_db.run_idempotent(
        f"withdrawal-create:{request_key}",
        "withdrawal_create",
        _apply,
        lock_key=f"user:{user_id}",
    )


def settle_deposit(db, deposit_id, status, note=""):
    """Approve/reject one deposit exactly once on the authoritative backend."""
    if hasattr(db, "settle_deposit"):
        return db.settle_deposit(deposit_id, status, note)
    initial = db.collection("deposits").document(str(deposit_id)).get()
    lock_user_id = initial.to_dict().get("userId") if initial.exists else None

    def _apply(transaction):
        ref = db.collection("deposits").document(str(deposit_id))
        doc = transaction.get(ref)
        if not doc.exists:
            return {"ok": False, "error": "not_found"}
        data = doc.to_dict()
        if data.get("status") != "pending":
            return _already_processed(data)
        user_id = data.get("userId")
        amount = float(data.get("amount", 0) or 0)
        if not math.isfinite(amount) or amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        update = {
            "status": status,
            "processedAt": datetime.now(tz=timezone.utc),
        }
        if note:
            update["adminNote"] = note
        transaction.update(ref, update)
        if status == "approved" and user_id and amount > 0:
            user_ref = db.collection("users").document(str(user_id))
            transaction.update(user_ref, {
                "play_wallet": firestore_db.Increment(amount),
                "updated_at": datetime.now(tz=timezone.utc),
            })
        return _settlement_result(data, user_id, amount, status)

    return firestore_db.run_idempotent(
        f"deposit-settlement:{deposit_id}:{status}",
        "deposit_settlement",
        _apply,
        lock_key=f"user:{lock_user_id}" if status == "approved" and lock_user_id else None,
    )


def settle_withdrawal(db, withdrawal_id, status, note=""):
    """Approve/reject one withdrawal exactly once on the authoritative backend."""
    if hasattr(db, "settle_withdrawal"):
        return db.settle_withdrawal(withdrawal_id, status, note)
    initial = db.collection("withdrawals").document(str(withdrawal_id)).get()
    lock_user_id = initial.to_dict().get("userId") if initial.exists else None

    def _apply(transaction):
        ref = db.collection("withdrawals").document(str(withdrawal_id))
        doc = transaction.get(ref)
        if not doc.exists:
            return {"ok": False, "error": "not_found"}
        data = doc.to_dict()
        if data.get("status") != "pending":
            return _already_processed(data)
        user_id = data.get("userId")
        amount = float(data.get("amount", 0) or 0)
        if not math.isfinite(amount) or amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        update = {
            "status": status,
            "processedAt": datetime.now(tz=timezone.utc),
        }
        if note:
            update["adminNote"] = note
        transaction.update(ref, update)
        if status == "rejected" and user_id and amount > 0:
            user_ref = db.collection("users").document(str(user_id))
            transaction.update(user_ref, {
                "play_wallet": firestore_db.Increment(amount),
                "updated_at": datetime.now(tz=timezone.utc),
            })
        return _settlement_result(data, user_id, amount, status)

    return firestore_db.run_idempotent(
        f"withdrawal-settlement:{withdrawal_id}:{status}",
        "withdrawal_settlement",
        _apply,
        lock_key=f"user:{lock_user_id}" if status == "rejected" and lock_user_id else None,
    )
