"""送信前チェッカー: Outlook の .msg ファイルを読み、宛先・本文・添付を確認する簡易アプリ。

使い方:
    python msg_checker.py              GUI で起動
    python msg_checker.py A.msg        GUI で起動してすぐチェック
    python msg_checker.py --cli A.msg  結果を画面に文字で出す

.msg を読むだけで、送信や書き換えはしません。
"""

import difflib
import io
import json
import re
import sys
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import extract_msg

try:
    import pypdf
except ImportError:  # PDF の中身チェックだけ無効にする
    pypdf = None

CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULT_CONFIG = {
    "own_domains": "",   # 自社ドメイン（社内宛ては「情報」扱い）
    "customers": "",       # お客様リスト（手入力）。1 行 1 社で「ドメイン = 名前, 別名」
    "customers_xlsx": "",  # お客様リストの Excel。設定されていればこちらを毎回読み直す
    "own_names": "",       # 自社名など、添付に出てきても問題ない会社名
    "ng_words": "",        # 入っていたら NG の語（社外秘 など）
    "store_dirs": "",      # 添付置き場（; 区切り）。パスワード付き添付の元ファイルを探す
}


@dataclass
class Customer:
    domains: list
    names: list

    @property
    def label(self):
        return self.names[0] if self.names else self.domains[0]


def parse_customers_text(text):
    """手入力のお客様リストを読む。例: a-corp.co.jp, a-corp.com = 株式会社エー, エー社"""
    customers = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        left, _, right = line.partition("=")
        domains = [d.lower().lstrip("@") for d in split_list(left)]
        if domains:
            customers.append(Customer(domains, split_list(right)))
    return customers


def customers_to_text(customers):
    return "\n".join(f"{', '.join(c.domains)} = {', '.join(c.names)}" for c in customers)


def split_domains(value):
    """「taro@a.co.jp」のようなメールアドレスが書かれていてもドメインだけ取り出す。"""
    return [d.rsplit("@", 1)[-1].strip().lower() for d in re.split(r"[,、;；\s]+", value or "") if d.strip()]


def read_customers_xlsx(path):
    """Excel のお客様リストを読む。見出し行の「ドメイン」列と「〜名」「別名」などの列を使う。

    見出しが無いときは A 列 = お客様名、B 列 = ドメイン、C 列以降 = 別名 とみなす。
    戻り値: (お客様一覧, ドメインが空で読み飛ばした行の番号)
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()

    header, dom_cols, name_cols = -1, [1], None
    for i, row in enumerate(rows[:5]):
        cells = [str(c or "") for c in row]
        found = [j for j, c in enumerate(cells) if re.search(r"ドメイン|domain|メール|mail", c, re.I)]
        if found:
            header, dom_cols = i, found
            name_cols = [j for j, c in enumerate(cells)
                         if j not in found and re.search(r"名|社|略称|顧客|お客様|name", c, re.I)]
            break
    if name_cols is None:
        width = max((len(r) for r in rows), default=0)
        name_cols = [j for j in range(width) if j not in dom_cols]

    customers, skipped = [], []
    for n, row in enumerate(rows[header + 1:], start=header + 2):
        def cell(j):
            return str(row[j]).strip() if j < len(row) and row[j] is not None else ""
        domains = [d for j in dom_cols for d in split_domains(cell(j))]
        names = [x for j in name_cols for x in split_list(cell(j))]
        if not domains and not names:
            continue
        if not domains:
            skipped.append(n)
            continue
        customers.append(Customer(domains, names))
    return customers, skipped


def write_customers_template(path):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "お客様リスト"
    ws.append(["お客様名", "ドメイン", "別名・略称（資料やファイル名での書き方）"])
    ws.append(["株式会社エー", "a-corp.co.jp", "エー社, ㈱エー, A社"])
    ws.append(["株式会社ビー", "b-corp.co.jp, b-corp.com", "ビー社"])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    for col, width in zip("ABC", (24, 32, 44)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    wb.save(path)


def load_customers(cfg):
    """お客様リストを読む。戻り値: (お客様一覧, 問題点のメッセージ)"""
    path = (cfg.get("customers_xlsx") or "").strip().strip('"')
    if not path:
        return parse_customers_text(cfg.get("customers")), []
    if not Path(path).is_file():
        return [], [f"お客様リストの Excel が見つかりません: {path}"]
    try:
        customers, skipped = read_customers_xlsx(path)
    except Exception as e:  # 開いたままで読めない、壊れているなど
        return [], [f"お客様リストの Excel を読めませんでした: {e}"]
    problems = []
    if skipped:
        problems.append("ドメインが空の行は読み飛ばしました（Excel の行番号）: " + ", ".join(map(str, skipped)))
    if not customers:
        problems.append(f"お客様リストの Excel に読み取れる行がありません: {path}")
    return customers, problems


# ---------------------------------------------------------------- 会社名の読み取り（リストに無い会社の検出）

LEGAL_FORMS = (r"株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|公益社団法人|公益財団法人"
               r"|学校法人|医療法人|社会福祉法人|独立行政法人|\(株\)|\(有\)|\(同\)")
NAME_CHARS = r"[^\s、。,，()（）「」『』【】<>:：/／\"'|]"
COMPANY_PREFIX_RE = re.compile(rf"(?:{LEGAL_FORMS})[ 　]*({NAME_CHARS}{{1,20}})")  # 改行はまたがない
COMPANY_SUFFIX_RE = re.compile(rf"({NAME_CHARS}{{1,15}})[ 　]*(?:{LEGAL_FORMS})")
NAME_STOP_RE = re.compile(r"御中|様|殿|宛|向け|より|から|です|では|への|の|は|が|を|へ|に|と|で|も|や")
NAME_CHAR_RE = re.compile(NAME_CHARS)


def extract_companies(text):
    """「株式会社〇〇」「〇〇株式会社」「(株)〇〇」の形の会社名を拾う。"""
    t = unicodedata.normalize("NFKC", text or "")
    found = []
    for m in COMPANY_PREFIX_RE.finditer(t):
        name = NAME_STOP_RE.split(m.group(1), 1)[0]  # 「〇〇御中」「〇〇の」などの後ろを切る
        if len(name) >= 2:
            found.append(name)
    for m in COMPANY_SUFFIX_RE.finditer(t):
        after = t[m.end():m.end() + 2]
        if after and NAME_CHAR_RE.match(after) and not NAME_STOP_RE.match(after):
            continue  # 「〇〇 株式会社△△」の △△ 側の会社なので、前の語は会社名ではない
        name = NAME_STOP_RE.split(m.group(1))[-1]   # 「本書は〇〇」などの前を切る
        if len(name) >= 2:
            found.append(name)
    return list(dict.fromkeys(found))


def company_core(name):
    return re.sub(rf"{LEGAL_FORMS}|\s", "", norm(name))


def same_company(a, b):
    ca, cb = company_core(a), company_core(b)
    return len(ca) >= 2 and len(cb) >= 2 and (ca in cb or cb in ca)


def guess_addressee(subject, body, own_names):
    """お客様リストで判定できないとき、件名と本文（引用部分より前）の会社名を宛先とみなす。"""
    cut = len(body)
    for m in QUOTE_MARKERS:
        i = body.find(m)
        if i >= 0:
            cut = min(cut, i)
    names = extract_companies(subject + "\n" + body[:cut])
    return [n for n in names if not any(same_company(n, o) for o in own_names)]

NG, WARN, OK, INFO = "NG", "注意", "OK", "情報"
LEVEL_ORDER = {NG: 0, WARN: 1, OK: 2, INFO: 3}

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
OOXML_EXTS = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"}
LEGACY_OFFICE_EXTS = {".doc", ".xls", ".ppt"}
DANGEROUS_EXTS = {".exe", ".bat", ".cmd", ".com", ".scr", ".js", ".vbs", ".ps1", ".msi", ".lnk", ".hta"}

PLACEHOLDER_RE = re.compile(r"○○|〇〇|××|ＸＸ|XX|xxx|TBD|TODO|要確認|＊＊|\*\*\*|【\s*】")
QUOTE_MARKERS = ["-----Original Message-----", "差出人:", "差出人：", "送信日時:", "送信日時：",
                 "From:", "Sent:"]
QUOTE_LINE_RE = re.compile(r"^>", re.M)
PASSWORD_RE = re.compile(r"(パスワード|PW|ＰＷ|Password|pass)\s*[:：は]\s*\S{4,}", re.IGNORECASE)


@dataclass
class Finding:
    level: str
    area: str
    message: str


def norm(text):
    """全角/半角・大文字/小文字の違いを無視して比較するための正規化。"""
    return unicodedata.normalize("NFKC", text or "").lower()


def split_list(value):
    return [w.strip() for w in re.split(r"[,、\n]", value or "") if w.strip()]


def find_words(text, words):
    t = norm(text)
    return [w for w in words if norm(w) in t]


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    # 旧形式（お客様 1 社だけの設定）を引き継ぐ
    old_domains = cfg.pop("customer_domains", "")
    old_names = cfg.pop("customer_names", "")
    if old_domains and not cfg["customers"]:
        cfg["customers"] = f"{old_domains} = {old_names}"
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 宛先

def recipient_type_name(r):
    t = getattr(r, "type", None)
    value = getattr(t, "value", t)
    return {1: "To", 2: "Cc", 3: "Bcc"}.get(value, "To")


def domain_of(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def domain_matches(domain, patterns):
    return any(domain == p or domain.endswith("." + p) for p in patterns)


def check_recipients(msg, cfg, customers, out):
    """宛先を確認し、(宛先一覧, 宛先になっているお客様) を返す。"""
    own = [d.lower().lstrip("@") for d in split_list(cfg["own_domains"])]
    all_domains = [d for c in customers for d in c.domains]
    targets = []

    recipients = []
    for r in msg.recipients:
        if getattr(getattr(r, "type", None), "value", None) == 0:  # 差出人の記録は宛先ではない
            continue
        email = (getattr(r, "email", "") or "").strip()
        name = (getattr(r, "name", "") or "").strip()
        recipients.append((recipient_type_name(r), name, email))

    if not recipients:
        out.append(Finding(NG, "宛先", "宛先がありません"))
        return recipients, targets

    external_domains = set()
    for kind, name, email in recipients:
        label = f"{kind}: {name} <{email}>" if name else f"{kind}: {email}"
        domain = domain_of(email)
        if not domain:
            out.append(Finding(WARN, "宛先", f"{label} … メールアドレスとして読めません（アドレス帳の名前だけの可能性）"))
            continue
        if own and domain_matches(domain, own):
            out.append(Finding(INFO, "宛先", f"{label} … 社内"))
            continue
        external_domains.add(domain)
        matched = [c for c in customers if domain_matches(domain, c.domains)]
        if matched:
            out.append(Finding(OK, "宛先", f"{label} … {matched[0].label}"))
            targets += [c for c in matched if c not in targets]
            continue
        similar = [d for d in all_domains if difflib.SequenceMatcher(None, domain, d).ratio() >= 0.8]
        if similar:
            out.append(Finding(NG, "宛先", f"{label} … {similar[0]} に似ていますが違うドメインです（打ち間違いの可能性）"))
        elif customers:
            out.append(Finding(NG, "宛先", f"{label} … お客様リストにない社外アドレスです（正しい宛先ならリストに登録してください）"))
        else:
            out.append(Finding(INFO, "宛先", f"{label} … 社外（お客様リスト未登録のため判定なし）"))

    if len(targets) > 1:
        out.append(Finding(NG, "宛先", "複数のお客様が同じメールの宛先に入っています: "
                           + "、".join(c.label for c in targets)))
    if not customers and len(external_domains) > 1:
        out.append(Finding(WARN, "宛先", "社外ドメインが複数あります: " + ", ".join(sorted(external_domains))))
    if any(kind == "Bcc" for kind, _, _ in recipients):
        out.append(Finding(WARN, "宛先", "Bcc が入っています。意図したものか確認してください"))
    if not customers:
        out.append(Finding(WARN, "設定", "お客様リストを登録すると、宛先違いや他社宛ての資料の混入を自動で NG にできます"))
    return recipients, targets


def check_customer_names(area, text, targets, others, out, what="中身"):
    """宛先のお客様の名前があるか、ほかのお客様の名前が混ざっていないかを確認する。"""
    t = norm(text)
    # 宛先のお客様の名前を消してから探す（「A社」と「AA社」のような名前の重なり対策）
    for c in targets:
        for n in sorted(c.names, key=len, reverse=True):
            t = t.replace(norm(n), " ")
    for c in others:
        hits = [n for n in c.names if norm(n) in t]
        if hits:
            out.append(Finding(NG, area, f"{what}に宛先ではないお客様「{c.label}」の名前があります: " + "、".join(hits)))

    names = [n for c in targets for n in c.names]
    if names and "ファイル名" not in what:  # ファイル名にお客様名が無いのは普通なので求めない
        found = find_words(text, names)
        if found:
            out.append(Finding(OK, area, f"{what}に宛先のお客様名があります: " + "、".join(found)))
        else:
            out.append(Finding(WARN, area, f"{what}に宛先のお客様名（{targets[0].label}）が見当たりません"))


# ---------------------------------------------------------------- 件名・本文

def check_body(msg, cfg, attachments, targets, others, out):
    subject = msg.subject or ""
    body = msg.body or ""
    ng_words = split_list(cfg["ng_words"])

    if not subject.strip():
        out.append(Finding(NG, "件名", "件名が空です"))
    for w in find_words(subject, ng_words):
        out.append(Finding(NG, "件名", f"NG ワード「{w}」が入っています"))
    for w in find_words(body, ng_words):
        out.append(Finding(NG, "本文", f"NG ワード「{w}」が入っています"))

    check_customer_names("件名・本文", subject + "\n" + body, targets, others, out, what="件名・本文")

    placeholders = sorted(set(PLACEHOLDER_RE.findall(subject + "\n" + body)))
    if placeholders:
        out.append(Finding(WARN, "本文", "仮の文字が残っているかもしれません: " + " ".join(placeholders)))

    markers = [m for m in QUOTE_MARKERS if m in body]
    if QUOTE_LINE_RE.search(body):
        markers.append(">")
    if markers:
        out.append(Finding(WARN, "本文", "過去のやり取り（引用・転送）が含まれています。出してはいけない内容がないか確認してください"
                           f"（検出: {' '.join(markers)}）"))

    if PASSWORD_RE.search(body):
        out.append(Finding(WARN, "本文", "本文にパスワードらしき記載があります。添付と同じメールで送ってよいか確認してください"))

    real_attachments = [a for a in attachments if not a["inline"]]
    mentions = any(w in body for w in ("添付", "送付", "お送り")) or "attach" in norm(body)
    if mentions and not real_attachments:
        out.append(Finding(NG, "本文", "本文に「添付」とありますが、添付ファイルがありません"))
    if real_attachments and not mentions:
        out.append(Finding(WARN, "本文", "添付ファイルがありますが、本文で触れていません"))


# ---------------------------------------------------------------- 添付

def collect_attachments(msg):
    items = []
    for att in msg.attachments:
        name = (getattr(att, "longFilename", None) or getattr(att, "shortFilename", None)
                or getattr(att, "name", None) or "(名前なし)")
        data = getattr(att, "data", None)
        cid = getattr(att, "cid", None) or getattr(att, "contentId", None)
        hidden = bool(getattr(att, "hidden", False))
        items.append({
            "name": str(name),
            "data": data,
            "inline": bool(cid) and hidden,
        })
    return items


def xml_text(raw):
    return re.sub(r"<[^>]+>", "", raw.decode("utf-8", "ignore"))


def check_ooxml(name, filename, data, out):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        out.append(Finding(WARN, name, "Office ファイルとして開けませんでした"))
        return ""
    names = z.namelist()

    def read(path):
        return z.read(path) if path in names else b""

    core = read("docProps/core.xml").decode("utf-8", "ignore")
    app = read("docProps/app.xml").decode("utf-8", "ignore")
    props = []
    for tag, label in [("dc:creator", "作成者"), ("cp:lastModifiedBy", "最終更新者"), ("dc:title", "タイトル")]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", core, re.S)
        if m and m.group(1).strip():
            props.append(f"{label}={m.group(1).strip()}")
    m = re.search(r"<Company>(.*?)</Company>", app, re.S)
    if m and m.group(1).strip():
        props.append(f"会社={m.group(1).strip()}")
    if props:
        out.append(Finding(INFO, name, "プロパティ: " + "、".join(props) + "（出してよい名前か確認）"))

    text_parts = []
    ext = Path(filename).suffix.lower()

    if ext.startswith(".doc"):
        doc = read("word/document.xml")
        text_parts.append(xml_text(doc))
        if re.search(rb"<w:(ins|del)\b", doc):
            out.append(Finding(NG, name, "変更履歴が残っています（削除した文も相手に見えます）"))
        if b"<w:vanish/>" in doc:
            out.append(Finding(WARN, name, "隠し文字があります"))
        if "word/comments.xml" in names and b"<w:comment " in read("word/comments.xml"):
            out.append(Finding(WARN, name, "コメントが残っています"))
        for part in names:
            if re.match(r"word/(header|footer)\d*\.xml", part):
                text_parts.append(xml_text(read(part)))

    elif ext.startswith(".xls"):
        wb = read("xl/workbook.xml").decode("utf-8", "ignore")
        for m in re.finditer(r"<sheet\b[^>]*>", wb):
            tag = m.group(0)
            state = re.search(r'state="(\w+)"', tag)
            sheet = re.search(r'name="([^"]*)"', tag)
            if state and state.group(1) in ("hidden", "veryHidden"):
                kind = "完全に隠されたシート" if state.group(1) == "veryHidden" else "非表示シート"
                out.append(Finding(WARN, name, f"{kind}があります: {sheet.group(1) if sheet else '?'}"))
        hidden_rc = False
        for part in names:
            if re.match(r"xl/worksheets/sheet\d+\.xml", part):
                sx = read(part)
                if re.search(rb'<(row|col)\b[^>]*hidden="(1|true)"', sx):
                    hidden_rc = True
                text_parts.append(xml_text(sx))  # 数式や直接入力の文字
        if hidden_rc:
            out.append(Finding(WARN, name, "非表示の行または列があります"))
        if any(re.match(r"xl/(comments\d*|threadedComments/.*)\.xml", p) for p in names):
            out.append(Finding(WARN, name, "コメントが残っています"))
        if any(p.startswith("xl/externalLinks/") for p in names):
            out.append(Finding(WARN, name, "他のファイルへのリンクがあります（ファイル名やパスが見える場合があります）"))
        text_parts.append(xml_text(read("xl/sharedStrings.xml")))
        text_parts.append(wb)  # シート名

    elif ext.startswith(".ppt"):
        notes_text = ""
        for part in names:
            if re.match(r"ppt/slides/slide\d+\.xml", part):
                sx = read(part)
                text_parts.append(xml_text(sx))
                if re.search(rb'<p:sld\b[^>]*show="0"', sx):
                    out.append(Finding(WARN, name, f"非表示のスライドがあります: {Path(part).stem}"))
            elif re.match(r"ppt/notesSlides/notesSlide\d+\.xml", part):
                notes_text += xml_text(read(part))
        if re.sub(r"\s|\d", "", notes_text):
            out.append(Finding(WARN, name, "ノート（発表者メモ）に文字が入っています"))
            text_parts.append(notes_text)
        if any(p.startswith("ppt/comments") for p in names):
            out.append(Finding(WARN, name, "コメントが残っています"))

    if ext.endswith("m"):
        out.append(Finding(WARN, name, "マクロ付きファイルです。お客様に送ってよいか確認してください"))
    return "\n".join(text_parts)


def check_pdf(name, data, out):
    """PDF を確認して文字を返す。パスワードで開けないときは None。"""
    if pypdf is None:
        out.append(Finding(INFO, name, "pypdf が無いため PDF の中身は確認していません"))
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as e:  # 壊れた PDF など
        out.append(Finding(WARN, name, f"PDF を開けませんでした: {e}"))
        return ""
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except Exception:
            opened = False
        if not opened:
            out.append(Finding(INFO, name, "パスワード保護あり"))
            return None
        out.append(Finding(INFO, name, "印刷・編集の制限がかかっています"))

    meta = reader.metadata or {}
    props = [f"{label}={meta.get(key)}" for key, label in
             [("/Author", "作成者"), ("/Title", "タイトル"), ("/Creator", "作成ソフト")] if meta.get(key)]
    if props:
        out.append(Finding(INFO, name, "プロパティ: " + "、".join(props)))

    texts, annots = [], 0
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            pass
        for a in page.get("/Annots") or []:
            try:
                if a.get_object().get("/Subtype") not in ("/Link", "/Widget"):
                    annots += 1
            except Exception:
                pass
    if annots:
        out.append(Finding(WARN, name, f"注釈（コメント・付箋・図形など）が {annots} 個あります"))
    text = "\n".join(texts)
    if not text.strip():
        out.append(Finding(INFO, name, "文字を読み取れません（画像の PDF）。中身は目で確認してください"))
    out.append(Finding(INFO, name, f"{len(reader.pages)} ページ。黒塗りがある場合は、文字が下に残っていないか確認してください"))
    return text


READ, LOCKED, UNSUPPORTED = "read", "locked", "unsupported"
STORE_FILE_LIMIT = 20000
# 「見積_pw.xlsx」「見積(パスワード付き).xlsx」なども元ファイル「見積.xlsx」と同じとみなす
STORE_SUFFIX_RE = re.compile(r"[\s_\-]*[(（\[［]?(pw|pass|password|パスワード付き?|パスワード|暗号化済み?|ロック)[)）\]］]?$")


@dataclass
class Context:
    cfg: dict
    targets: list
    others: list
    store: "FileStore"
    addressee: list  # 本文から読み取った宛先の会社名（リストで判定できないとき用）

    @property
    def ng_words(self):
        return split_list(self.cfg["ng_words"])

    @property
    def own_names(self):
        return split_list(self.cfg.get("own_names", ""))

    @property
    def known_names(self):
        """添付に出てきても問題ない会社名: 宛先のお客様・本文の宛名・自社。"""
        return [n for c in self.targets for n in c.names] + self.addressee + self.own_names


class FileStore:
    """添付置き場。パスワード付きで読めない添付の元ファイルを名前で探す。"""

    def __init__(self, dirs):
        self.dirs = []
        for d in dirs:
            p = Path(d.strip().strip('"'))
            if d.strip() and p.is_dir() and p not in self.dirs:
                self.dirs.append(p)
        self._index = None
        self.truncated = False

    @staticmethod
    def key(filename):
        p = Path(norm(Path(filename).name))
        return STORE_SUFFIX_RE.sub("", p.stem) + p.suffix

    def find(self, filename):
        if self._index is None:  # 必要になったときだけフォルダを見に行く
            self._index, count = {}, 0
            for d in self.dirs:
                for p in d.rglob("*"):
                    if count >= STORE_FILE_LIMIT:
                        self.truncated = True
                        break
                    if p.is_file():
                        count += 1
                        self._index.setdefault(self.key(p.name), []).append(p)
        return self._index.get(self.key(filename), [])


def zip_entry_name(info):
    """日本語 Windows で作った ZIP のファイル名（Shift_JIS）を読めるようにする。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp932")
    except UnicodeError:
        return info.filename


def check_text(area, text, ctx, out):
    for w in find_words(text, ctx.ng_words):
        out.append(Finding(NG, area, f"中身に NG ワード「{w}」が入っています"))
    check_customer_names(area, text, ctx.targets, ctx.others, out)

    # リストに無い会社名も拾う（リストにある他社は上で NG にしているので除く）
    registered_others = [n for c in ctx.others for n in c.names]
    unknown = [n for n in extract_companies(text)
               if not any(same_company(n, k) for k in ctx.known_names + registered_others)]
    if unknown:
        to = ctx.targets[0].label if ctx.targets else "、".join(ctx.addressee)
        out.append(Finding(WARN, area, (f"宛先（{to}）以外の" if to else "") + "会社名があります: " + "、".join(unknown[:10])
                           + "（別のお客様の資料ではないか確認。問題ない会社名は「自社名・除外」に登録）"))


def read_content(area, filename, data, ctx, out, use_store=True):
    """ファイルの中身を確認する。READ / LOCKED（パスワード付き）/ UNSUPPORTED を返す。"""
    ext = Path(filename).suffix.lower()
    text = None
    if ext in OOXML_EXTS:
        if data.startswith(OLE_MAGIC):
            out.append(Finding(INFO, area, "パスワード保護あり"))
            return LOCKED
        text = check_ooxml(area, filename, data, out)
    elif ext == ".pdf":
        text = check_pdf(area, data, out)
        if text is None:
            return LOCKED
    elif ext == ".zip":
        return check_zip(area, data, ctx, out, use_store)
    elif ext in (".txt", ".csv"):
        text = data.decode("cp932", "ignore") if b"\x00" not in data[:1000] else ""
    else:
        return UNSUPPORTED
    if text:
        check_text(area, text, ctx, out)
    return READ


def check_zip(area, data, ctx, out, use_store):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        out.append(Finding(WARN, area, "ZIP として開けませんでした"))
        return UNSUPPORTED
    infos = [i for i in z.infolist() if not i.is_dir()]
    inner = [zip_entry_name(i) for i in infos]
    out.append(Finding(INFO, area, "中身: " + "、".join(inner[:20]) + (" …" if len(inner) > 20 else "")))
    for w in find_words("\n".join(inner), ctx.ng_words):
        out.append(Finding(NG, area, f"ZIP 内のファイル名に NG ワード「{w}」が入っています"))
    check_customer_names(area, "\n".join(inner), ctx.targets, ctx.others, out, what="ZIP 内のファイル名")
    if any(i.flag_bits & 0x1 for i in infos):
        out.append(Finding(INFO, area, "パスワード付き ZIP です"))

    for info, name in zip(infos, inner):
        entry_area = f"{area} > {name}"
        if info.flag_bits & 0x1:
            if use_store:
                # AES 暗号化（方式 99）は CRC が 0 のことがあるので、そのときはサイズだけで照合する
                crc = info.CRC if not (info.compress_type == 99 and info.CRC == 0) else None
                check_with_store(entry_area, name, ctx, out, size=info.file_size, crc=crc)
            else:
                out.append(Finding(WARN, entry_area, "パスワード付きのため中身を確認できません"))
            continue
        try:
            entry = z.read(info)
        except Exception as e:
            out.append(Finding(WARN, entry_area, f"取り出せませんでした: {e}"))
            continue
        status = read_content(entry_area, name, entry, ctx, out, use_store)
        if status == LOCKED and use_store:
            check_with_store(entry_area, name, ctx, out)
        elif status == UNSUPPORTED and ctx.targets:
            out.append(Finding(WARN, entry_area, "この形式は中身を確認できません。開いて確認してください"))
    return READ


def check_with_store(area, filename, ctx, out, size=None, crc=None):
    """読めない添付の代わりに、置き場にある同じ名前の元ファイルで確認する。"""
    if not ctx.store.dirs:
        out.append(Finding(WARN, area, "中身を読めません。添付置き場を設定すると元ファイルで確認できます"))
        return
    candidates = ctx.store.find(filename)
    if ctx.store.truncated:
        out.append(Finding(WARN, "添付置き場", f"ファイルが多すぎるため、先頭の {STORE_FILE_LIMIT:,} 件だけ探しました"))
    if not candidates:
        out.append(Finding(WARN, area, f"中身を読めず、置き場にも元ファイル「{Path(filename).name}」が見つかりません。"
                           "開いて確認してください"))
        return

    if size is not None:  # パスワード付き ZIP の中身はサイズと CRC で同じファイルか照合できる
        same = []
        for p in candidates:
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            if len(raw) == size and (crc is None or zlib.crc32(raw) == crc):
                same.append(p)
        if same:
            how = "サイズと CRC" if crc is not None else "サイズ（この暗号化方式では CRC は照合できません）"
            out.append(Finding(OK if crc is not None else INFO, area, f"置き場の元ファイルと同じファイルです（{how}が一致）: {same[0]}"))
            candidates = same[:1]
        else:
            out.append(Finding(NG, area, "置き場に同じ名前のファイルはありますが、中身が一致しません（別の版や別のお客様のファイルの可能性）: "
                               + "、".join(str(p) for p in candidates)))
            return
    else:
        if len(candidates) > 1:
            out.append(Finding(WARN, area, "置き場に同じ名前のファイルが複数あります。どれを添付したか確認してください: "
                               + "、".join(str(p) for p in candidates)))
        out.append(Finding(WARN, area, "パスワード付きのため、置き場の同じ名前のファイルで代わりに確認しました。"
                           f"添付と同じ版かは確認できないので、置き場のファイルが送ったものと同じか確認してください: {candidates[0]}"))

    for p in candidates:
        try:
            raw = p.read_bytes()
        except OSError as e:
            out.append(Finding(WARN, area, f"置き場のファイルを読めませんでした: {e}"))
            continue
        store_area = f"{area}［置き場］"
        status = read_content(store_area, p.name, raw, ctx, out, use_store=False)
        if status == LOCKED:
            out.append(Finding(WARN, store_area, f"置き場のファイルもパスワード付きのため確認できません: {p}"))
        elif status == UNSUPPORTED and ctx.targets:
            out.append(Finding(WARN, store_area, "この形式は中身を確認できません。開いて確認してください"))


def check_attachments(attachments, ctx, out):
    ng_words = ctx.ng_words
    targets, others = ctx.targets, ctx.others
    real = [a for a in attachments if not a["inline"]]
    if not real:
        out.append(Finding(INFO, "添付", "添付ファイルはありません"))

    for a in attachments:
        name, data = a["name"], a["data"]
        if a["inline"]:
            out.append(Finding(INFO, name, "本文中の画像（署名のロゴなど）"))
            continue
        if isinstance(data, extract_msg.Message) or (data is not None and not isinstance(data, bytes)):
            out.append(Finding(WARN, name, "メールが添付されています。中のメールと添付も別途確認してください"))
            continue
        data = data or b""
        ext = Path(name).suffix.lower()
        out.append(Finding(INFO, name, f"添付ファイル（{len(data):,} バイト）"))

        for w in find_words(name, ng_words):
            out.append(Finding(NG, name, f"ファイル名に NG ワード「{w}」が入っています"))
        check_customer_names(name, name, targets, others, out, what="ファイル名")
        if ext in DANGEROUS_EXTS or re.search(r"\.\w+\.(exe|scr|bat|js|vbs)$", name, re.I):
            out.append(Finding(NG, name, "実行できる形式のファイルです"))
        if len(data) == 0:
            out.append(Finding(NG, name, "ファイルが空（0 バイト）です"))
            continue

        if ext in LEGACY_OFFICE_EXTS:
            out.append(Finding(WARN, name, "古い形式の Office ファイルのため中身は確認していません。開いて目で確認してください"))
            continue
        status = read_content(name, name, data, ctx, out)
        if status == LOCKED:
            check_with_store(name, name, ctx, out)
        elif status == UNSUPPORTED and targets:
            out.append(Finding(WARN, name, f"この形式は中身を読めないため、{targets[0].label} 向けの資料か自動では確認できません。開いて確認してください"))


# ---------------------------------------------------------------- まとめ

def run_checks(path, cfg):
    out = []
    msg = extract_msg.openMsg(str(path))
    try:
        info = {
            "subject": msg.subject or "",
            "sender": msg.sender or "",
            "body": msg.body or "",
        }
        attachments = collect_attachments(msg)
        customers, problems = load_customers(cfg)
        for p in problems:
            out.append(Finding(NG if not customers else WARN, "お客様リスト", p))
        info["recipients"], targets = check_recipients(msg, cfg, customers, out)
        others = [c for c in customers if c not in targets]

        addressee = []
        if not targets:
            # リストで宛先のお客様がわからないときは、本文の宛名（株式会社〇〇 御中 など）を手がかりにする
            addressee = guess_addressee(info["subject"], info["body"], split_list(cfg.get("own_names", "")))
            if addressee:
                out.append(Finding(INFO, "宛先の推定", "本文の宛名から宛先を「" + "、".join(addressee)
                                   + "」とみなし、添付にほかの会社名がないか確認します"))
            else:
                out.append(Finding(WARN, "宛先の推定", "お客様リストでも本文からも宛先の会社を特定できません。"
                                   "添付が正しいお客様向けか、開いて確認してください"))

        # .msg と同じフォルダは常に添付置き場として探す
        store = FileStore([str(Path(path).resolve().parent)] + re.split(r"[;\n]", cfg.get("store_dirs", "")))
        ctx = Context(cfg, targets, others, store, addressee)
        check_body(msg, cfg, attachments, targets, others, out)
        check_attachments(attachments, ctx, out)
        if store._index is not None:
            out.append(Finding(INFO, "添付置き場", "元ファイルを探した場所: " + "、".join(str(d) for d in store.dirs)))
    finally:
        msg.close()
    out.sort(key=lambda f: LEVEL_ORDER[f.level])
    return info, out


def summary_text(findings):
    n_ng = sum(f.level == NG for f in findings)
    n_warn = sum(f.level == WARN for f in findings)
    if n_ng:
        return f"NG {n_ng} 件 / 注意 {n_warn} 件 … このままでは送らないでください", NG
    if n_warn:
        return f"注意 {n_warn} 件 … 1 件ずつ確認してから送ってください", WARN
    return "自動チェックでは問題なし。最後に宛先と添付を目で確認してから送ってください", OK


def run_cli(path):
    sys.stdout.reconfigure(encoding="utf-8")
    info, findings = run_checks(path, load_config())
    print(f"件名: {info['subject']}")
    for kind, name, email in info["recipients"]:
        print(f"{kind}: {name} <{email}>")
    print("-" * 60)
    for f in findings:
        print(f"[{f.level}] {f.area}: {f.message}")
    print("-" * 60)
    print(summary_text(findings)[0])


# ---------------------------------------------------------------- GUI

def run_gui(initial_path=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    cfg = load_config()
    root = tk.Tk()
    root.title("送信前チェッカー（.msg）")
    root.geometry("1000x720")

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    path_var = tk.StringVar(value=initial_path or "")
    ttk.Label(top, text=".msg ファイル").grid(row=0, column=0, sticky="w")
    ttk.Entry(top, textvariable=path_var).grid(row=0, column=1, sticky="ew", padx=4)

    def browse():
        p = filedialog.askopenfilename(filetypes=[("Outlook メッセージ", "*.msg"), ("すべて", "*.*")])
        if p:
            path_var.set(p)
            check()

    ttk.Button(top, text="参照…", command=browse).grid(row=0, column=2)
    top.columnconfigure(1, weight=1)

    settings = ttk.LabelFrame(root, text="判定の設定（次回も使えるよう保存されます）", padding=8)
    settings.pack(fill="x", padx=8)
    # お客様リスト: Excel を読み込む（読み込んだ Excel はチェックのたびに読み直す）
    ttk.Label(settings, text="お客様リスト").grid(row=0, column=0, sticky="nw")
    xlsx_var = tk.StringVar(value=cfg.get("customers_xlsx", ""))
    list_frame = ttk.Frame(settings)
    list_frame.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4)
    xlsx_label = ttk.Label(list_frame, foreground="gray")
    xlsx_label.pack(anchor="w")
    customers_text = tk.Text(list_frame, height=4, wrap="none", font=("Meiryo UI", 10))
    customers_text.pack(fill="x")
    buttons = ttk.Frame(settings)
    buttons.grid(row=0, column=3, sticky="n", padx=4)

    def show_customers():
        path = xlsx_var.get()
        customers_text.configure(state="normal")
        customers_text.delete("1.0", "end")
        if path:
            customers, problems = load_customers({"customers_xlsx": path})
            customers_text.insert("1.0", customers_to_text(customers))
            customers_text.configure(state="disabled", background="#f0f0f0")
            xlsx_label.configure(text=f"Excel: {path}（{len(customers)} 社。リストの修正は Excel で）"
                                 + ("\n" + "\n".join(problems) if problems else ""),
                                 foreground="red" if problems else "gray")
        else:
            customers_text.insert("1.0", cfg.get("customers", ""))
            customers_text.configure(background="white")
            xlsx_label.configure(text="Excel を読み込むか、ここに 1 行 1 社「ドメイン = お客様名, 別名」で入力",
                                 foreground="gray")

    def load_xlsx():
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm"), ("すべて", "*.*")])
        if p:
            xlsx_var.set(str(Path(p)))
            show_customers()

    def make_template():
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="お客様リスト.xlsx",
                                         filetypes=[("Excel", "*.xlsx")])
        if not p:
            return
        try:
            write_customers_template(p)
        except OSError as e:
            messagebox.showerror("エラー", f"保存できませんでした:\n{e}")
            return
        xlsx_var.set(str(Path(p)))
        show_customers()
        if messagebox.askyesno("ひな形", "ひな形を作りました。Excel で開いて編集しますか？\n（例の 2 行は消してから使ってください）"):
            import os
            os.startfile(p)

    def clear_xlsx():
        if not xlsx_var.get():
            return
        cfg["customers"] = customers_text.get("1.0", "end").strip()  # 読み込んだ内容を手入力欄に残す
        xlsx_var.set("")
        show_customers()

    ttk.Button(buttons, text="Excel 読み込み…", command=load_xlsx).pack(fill="x")
    ttk.Button(buttons, text="ひな形を作る…", command=make_template).pack(fill="x", pady=2)
    ttk.Button(buttons, text="Excel 解除", command=clear_xlsx).pack(fill="x")
    show_customers()

    fields = [
        ("ng_words", "NG ワード", "カンマ区切り 例: 社外秘, 社内限り"),
        ("own_names", "自社名・除外", "添付に出ても問題ない会社名 例: 自社名, 取引先メーカー名"),
        ("own_domains", "自社ドメイン", "例: mycompany.co.jp"),
        ("store_dirs", "添付置き場", "; 区切りで複数可。.msg と同じフォルダも自動で探します"),
    ]
    vars_ = {}
    for i, (key, label, hint) in enumerate(fields, start=1):
        ttk.Label(settings, text=label).grid(row=i, column=0, sticky="w")
        vars_[key] = tk.StringVar(value=cfg.get(key, ""))
        ttk.Entry(settings, textvariable=vars_[key]).grid(row=i, column=1, sticky="ew", padx=4, pady=1)
        ttk.Label(settings, text=hint, foreground="gray").grid(row=i, column=2, sticky="w")

    def add_store_dir():
        d = filedialog.askdirectory()
        if d:
            current = [s for s in vars_["store_dirs"].get().split(";") if s.strip()]
            vars_["store_dirs"].set(";".join(current + [str(Path(d))]))

    ttk.Button(settings, text="フォルダ追加…", command=add_store_dir).grid(row=len(fields), column=3, padx=4)
    settings.columnconfigure(1, weight=1)

    summary_var = tk.StringVar(value="ファイルを選んで「チェック」を押してください")
    bar = ttk.Frame(root, padding=8)
    bar.pack(fill="x")
    summary = tk.Label(bar, textvariable=summary_var, font=("Meiryo UI", 12, "bold"), anchor="w")
    summary.pack(side="left", fill="x", expand=True)

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    tab_result = ttk.Frame(nb)
    nb.add(tab_result, text="チェック結果")
    tree = ttk.Treeview(tab_result, columns=("level", "area", "message"), show="headings")
    for col, label, width in [("level", "判定", 60), ("area", "対象", 200), ("message", "内容", 700)]:
        tree.heading(col, text=label)
        tree.column(col, width=width, stretch=(col == "message"))
    sb = ttk.Scrollbar(tab_result, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    colors = {NG: "#ffd6d6", WARN: "#fff1c2", OK: "#dcf5dc", INFO: "#ffffff"}
    for level, color in colors.items():
        tree.tag_configure(level, background=color)

    tab_body = ttk.Frame(nb)
    nb.add(tab_body, text="件名・宛先・本文")
    body_text = tk.Text(tab_body, wrap="word")
    body_text.pack(fill="both", expand=True)

    def check():
        path = path_var.get().strip().strip('"')
        if not path:
            browse()
            return
        if not Path(path).is_file():
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return
        for key, var in vars_.items():
            cfg[key] = var.get()
        cfg["customers_xlsx"] = xlsx_var.get()
        if xlsx_var.get():
            show_customers()  # Excel の最新の内容を表示し直す
        else:
            cfg["customers"] = customers_text.get("1.0", "end").strip()
        try:
            save_config(cfg)
        except OSError:
            pass
        try:
            info, findings = run_checks(path, cfg)
        except Exception as e:
            messagebox.showerror("エラー", f".msg を読み込めませんでした:\n{e}")
            return

        tree.delete(*tree.get_children())
        for f in findings:
            tree.insert("", "end", values=(f.level, f.area, f.message), tags=(f.level,))
        text, level = summary_text(findings)
        summary_var.set(text)
        summary.configure(bg=colors[level] if level != OK else colors[OK])

        body_text.delete("1.0", "end")
        lines = [f"件名: {info['subject']}", f"差出人: {info['sender']}"]
        lines += [f"{k}: {n} <{e}>" for k, n, e in info["recipients"]]
        body_text.insert("1.0", "\n".join(lines) + "\n" + "-" * 60 + "\n" + info["body"])

    ttk.Button(bar, text="チェック", command=check).pack(side="right")
    root.bind("<Return>", lambda e: None if isinstance(e.widget, tk.Text) else check())
    if initial_path:
        root.after(100, check)
    root.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        run_cli(args[1])
    else:
        run_gui(args[0] if args else None)
