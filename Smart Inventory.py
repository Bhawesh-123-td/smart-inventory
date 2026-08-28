import sqlite3, shutil, csv, sys, os, re
from pathlib import Path
from datetime import datetime, date as ad_date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP=Path.home()/"SmartInventory"; APP.mkdir(exist_ok=True)
DB=APP/"inventory.db"; BACK=APP/"backups"; EXP=APP/"exports"
BACK.mkdir(exist_ok=True); EXP.mkdir(exist_ok=True)

def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name

db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
db.execute("""CREATE TABLE IF NOT EXISTS purchases(
id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,vendor TEXT,pan TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS sales(
id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS expenditures(
id INTEGER PRIMARY KEY,date TEXT,category TEXT,description TEXT,amount REAL,created TEXT)""")
for table in ("purchases","sales","expenditures"):
    cols={r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
    if "bs_date" not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN bs_date TEXT")
# Unit of measure migration: preserve existing data as pcs and normalize blanks.
for table in ("purchases","sales"):
    cols={r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
    if "unit" not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN unit TEXT DEFAULT 'pcs'")
    db.execute(f"UPDATE {table} SET unit='pcs' WHERE unit IS NULL OR trim(unit)=''")
db.execute("""CREATE TRIGGER IF NOT EXISTS purchases_validate_insert BEFORE INSERT ON purchases BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
db.execute("""CREATE TRIGGER IF NOT EXISTS purchases_validate_update BEFORE UPDATE ON purchases BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
db.execute("""CREATE TRIGGER IF NOT EXISTS sales_validate_insert BEFORE INSERT ON sales BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
db.execute("""CREATE TRIGGER IF NOT EXISTS sales_validate_update BEFORE UPDATE ON sales BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
db.execute("""CREATE TRIGGER IF NOT EXISTS expenditures_validate_insert BEFORE INSERT ON expenditures BEGIN SELECT CASE WHEN NEW.amount<0 THEN RAISE(ABORT,'Amount cannot be negative') WHEN trim(NEW.category)='' THEN RAISE(ABORT,'Category is required') END; END""")
db.execute("""CREATE TRIGGER IF NOT EXISTS expenditures_validate_update BEFORE UPDATE ON expenditures BEGIN SELECT CASE WHEN NEW.amount<0 THEN RAISE(ABORT,'Amount cannot be negative') WHEN trim(NEW.category)='' THEN RAISE(ABORT,'Category is required') END; END""")
db.commit()

# Optional sales/customer fields for credit tracking.
sale_cols={r["name"] for r in db.execute("PRAGMA table_info(sales)")}
for col, definition in [
    ("customer","TEXT DEFAULT ''"),("payment_status","TEXT DEFAULT 'Cash'"),
    ("paid","REAL DEFAULT 0"),("due_date","TEXT DEFAULT ''")]:
    if col not in sale_cols:
        db.execute(f"ALTER TABLE sales ADD COLUMN {col} {definition}")
db.execute("UPDATE sales SET payment_status='Cash' WHERE payment_status IS NULL OR payment_status=''")
# Older rows predate credit tracking: treat Cash sales as fully paid.
db.execute("UPDATE sales SET paid=price*qty WHERE paid IS NULL OR (payment_status='Cash' AND paid=0)")
db.commit()

# ---------------- Professional Accounting Layer ----------------
db.execute("""CREATE TABLE IF NOT EXISTS accounts(
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    parent_code TEXT DEFAULT '',
    opening_balance REAL DEFAULT 0,
    active INTEGER DEFAULT 1,
    created TEXT NOT NULL
)""")
db.execute("""CREATE TABLE IF NOT EXISTS journal_entries(
    id INTEGER PRIMARY KEY,
    entry_date TEXT NOT NULL,
    reference TEXT DEFAULT '',
    description TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    source_id INTEGER DEFAULT 0,
    created TEXT NOT NULL
)""")
db.execute("""CREATE TABLE IF NOT EXISTS journal_lines(
    id INTEGER PRIMARY KEY,
    journal_id INTEGER NOT NULL,
    account_code TEXT NOT NULL,
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    memo TEXT DEFAULT '',
    FOREIGN KEY(journal_id) REFERENCES journal_entries(id)
)""")
db.execute("""CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY,
    payment_date TEXT NOT NULL,
    party_type TEXT NOT NULL,
    party TEXT NOT NULL,
    amount REAL NOT NULL,
    method TEXT DEFAULT 'Cash',
    direction TEXT NOT NULL,
    reference TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created TEXT NOT NULL
)""")
db.execute("""CREATE TABLE IF NOT EXISTS accounting_periods(
    id INTEGER PRIMARY KEY,
    period_name TEXT UNIQUE NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT DEFAULT 'Open'
)""")
for code,name,typ,parent in [
    ("1000","Cash","Asset",""),("1010","Bank","Asset",""),("1020","Accounts Receivable","Asset",""),
    ("1100","Inventory","Asset",""),("2000","Accounts Payable","Liability",""),
    ("3000","Owner Equity","Equity",""),("4000","Sales Revenue","Income",""),
    ("4100","Other Income","Income",""),("5000","Cost of Goods Sold","Expense",""),
    ("6000","Operating Expenses","Expense","")]:
    db.execute("""INSERT OR IGNORE INTO accounts(code,name,account_type,parent_code,created)
                  VALUES(?,?,?,?,?)""",
               (code,name,typ,parent,datetime.now().isoformat(timespec="seconds")))
db.execute("CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date)")
db.execute("CREATE INDEX IF NOT EXISTS idx_journal_account ON journal_lines(account_code)")
db.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date)")
db.commit()

def M(x): return f"Rs. {float(x or 0):,.2f}"
def Q(x): return f"{float(x or 0):,.2f}".rstrip("0").rstrip(".")
def N(x): return x.strip().lower()
BS_DATA = {2070: [31, 31, 31, 32, 31, 31, 29, 30, 30, 29, 30, 30], 2071: [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30], 2072: [31, 32, 31, 32, 31, 30, 30, 29, 30, 29, 30, 30], 2073: [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 31], 2074: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30], 2075: [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30], 2076: [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 30], 2077: [31, 32, 31, 32, 31, 30, 30, 30, 29, 30, 29, 31], 2078: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30], 2079: [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30], 2080: [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 30], 2081: [31, 31, 32, 32, 31, 30, 30, 30, 29, 30, 30, 30], 2082: [30, 32, 31, 32, 31, 30, 30, 30, 29, 30, 30, 30], 2083: [31, 31, 32, 31, 31, 30, 30, 30, 29, 30, 30, 30], 2084: [31, 31, 32, 31, 31, 30, 30, 30, 29, 30, 30, 30], 2085: [31, 32, 31, 32, 30, 31, 30, 30, 29, 30, 30, 30], 2086: [30, 32, 31, 32, 31, 30, 30, 30, 29, 30, 30, 30], 2087: [31, 31, 32, 31, 31, 31, 30, 30, 29, 30, 30, 30], 2088: [30, 31, 32, 32, 30, 31, 30, 30, 29, 30, 30, 30], 2089: [30, 32, 31, 32, 31, 30, 30, 30, 29, 30, 30, 30], 2090: [30, 32, 31, 32, 31, 30, 30, 30, 29, 30, 30, 30], 2091: [31, 31, 32, 31, 31, 31, 30, 30, 29, 30, 30, 30], 2092: [31, 31, 32, 32, 31, 30, 30, 30, 29, 30, 30, 30]}
BS_STARTS = {2077: ad_date(2020,4,13)}
for _y in range(2076,2069,-1):
    BS_STARTS[_y] = BS_STARTS[_y+1] - __import__("datetime").timedelta(days=sum(BS_DATA[_y]))
for _y in range(2077,2092):
    BS_STARTS[_y+1] = BS_STARTS[_y] + __import__("datetime").timedelta(days=sum(BS_DATA[_y]))

def ad_to_bs(value):
    try:
        d=ad_date.fromisoformat(value.strip())
        y=max((yy for yy,sd in BS_STARTS.items() if sd <= d), default=None)
        if y is None or y not in BS_DATA: return ""
        days=(d-BS_STARTS[y]).days
        m=1
        while days >= BS_DATA[y][m-1]:
            days -= BS_DATA[y][m-1]; m += 1
        return f"{y:04d}-{m:02d}-{days+1:02d}"
    except Exception:
        return ""

def bs_to_ad(value):
    try:
        y,m,d=[int(x) for x in value.strip().split("-")]
        if y not in BS_DATA or not 1 <= m <= 12 or not 1 <= d <= BS_DATA[y][m-1]: return ""
        days=sum(BS_DATA[y][:m-1])+d-1
        return str(BS_STARTS[y] + __import__("datetime").timedelta(days=days))
    except Exception:
        return ""

def normalize_dates(e, changed=None, show_error=False):
    """Keep AD and B.S. dates synchronized and reject inconsistent pairs."""
    ad=e.get("date").get().strip() if e.get("date") else ""
    bs=e.get("bs_date").get().strip() if e.get("bs_date") else ""
    try:
        if changed == "ad":
            if not ad: raise ValueError("AD date is required.")
            converted=ad_to_bs(ad)
            if not converted: raise ValueError("Invalid or unsupported AD date.")
            e["bs_date"].delete(0,"end"); e["bs_date"].insert(0,converted)
            return ad, converted
        if changed == "bs":
            if not bs: raise ValueError("Nepali date is required.")
            converted=bs_to_ad(bs)
            if not converted: raise ValueError("Invalid or unsupported Nepali B.S. date.")
            e["date"].delete(0,"end"); e["date"].insert(0,converted)
            return converted, bs
        if ad and bs:
            expected=ad_to_bs(ad)
            if not expected or expected != bs:
                raise ValueError(f"Dates do not match. AD {ad} corresponds to B.S. {expected or 'an invalid date'}.")
            return ad, bs
        if ad:
            converted=ad_to_bs(ad)
            if not converted: raise ValueError("Invalid or unsupported AD date.")
            e["bs_date"].delete(0,"end"); e["bs_date"].insert(0,converted)
            return ad, converted
        if bs:
            converted=bs_to_ad(bs)
            if not converted: raise ValueError("Invalid or unsupported Nepali B.S. date.")
            e["date"].delete(0,"end"); e["date"].insert(0,converted)
            return converted, bs
        raise ValueError("Enter a date.")
    except ValueError as ex:
        if show_error: messagebox.showerror("Invalid dates",str(ex))
        raise

def _date_key(ad, created=""):
    try: return (ad_date.fromisoformat(ad), created or "")
    except Exception: return (ad_date.max, created or "")

def date_fields(parent, row, e, ad_value="", bs_value=""):
    tk.Label(parent,text="AD Date",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).grid(row=row,column=0,sticky="w",padx=(24,12),pady=7)
    e["date"]=tk.Entry(parent,relief="flat",bg="#f8f6fa",font=("Segoe UI",10),insertbackground="#24202a",highlightbackground="#d8d0dc",highlightthickness=1)
    e["date"].grid(row=row,column=1,sticky="ew",padx=(0,24),pady=7,ipady=5)
    e["date"].insert(0,ad_value)
    tk.Label(parent,text="Nepali Date (B.S.)",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).grid(row=row+1,column=0,sticky="w",padx=(24,12),pady=7)
    e["bs_date"]=tk.Entry(parent,relief="flat",bg="#f8f6fa",font=("Segoe UI",10),insertbackground="#24202a",highlightbackground="#d8d0dc",highlightthickness=1)
    e["bs_date"].grid(row=row+1,column=1,sticky="ew",padx=(0,24),pady=7,ipady=5)
    e["bs_date"].insert(0,bs_value or ad_to_bs(ad_value))
    e["_last_date_field"]=None
    e["date"].bind("<KeyRelease>",lambda _ : _mark_date_change(e,"ad"))
    e["bs_date"].bind("<KeyRelease>",lambda _ : _mark_date_change(e,"bs"))
    e["date"].bind("<FocusOut>",lambda _ : _sync_date_field(e,"ad"))
    e["bs_date"].bind("<FocusOut>",lambda _ : _sync_date_field(e,"bs"))

def _mark_date_change(e, which):
    e["_last_date_field"]=which
    widget=e["date"] if which=="ad" else e["bs_date"]
    value=widget.get().strip()
    if which=="ad": converted=ad_to_bs(value)
    else: converted=bs_to_ad(value)
    if converted:
        target=e["bs_date"] if which=="ad" else e["date"]
        target.delete(0,"end"); target.insert(0,converted)

def _sync_date_field(e, which):
    try: normalize_dates(e, changed=which, show_error=False)
    except ValueError: pass


# Backfill B.S. dates for records created before dual-date support.
for table in ("purchases","sales","expenditures"):
    for r in db.execute(f"SELECT id,date,bs_date FROM {table} WHERE bs_date IS NULL OR bs_date=''"):
        b=ad_to_bs(r["date"])
        if b: db.execute(f"UPDATE {table} SET bs_date=? WHERE id=?",(b,r["id"]))
db.commit()

def calc():
    """Calculate stock and weighted-average COGS in true chronological order.

    Purchases and sales are merged by transaction AD date, then created/id as a
    stable tie-breaker. A sale uses the weighted-average cost that existed
    immediately BEFORE that sale, so future purchases cannot change past COGS.
    """
    products={}; rev=cogs=spent=0.0
    rows=[]
    for p in db.execute("select * from purchases"):
        rows.append((p["date"],p["created"] or "",0,p["id"],p))
    for s in db.execute("select * from sales"):
        rows.append((s["date"],s["created"] or "",1,s["id"],s))
    rows.sort(key=lambda x: (_date_key(x[0],x[1]), x[2], x[3]))
    sale_cogs={}
    for _,_,typ,rid,row in rows:
        unit=str(row["unit"] or "pcs").strip() or "pcs"; k=(N(row["product"]),N(unit)); r=products.setdefault(k,{"name":row["product"],"unit":unit,"qty":0.0,"sold":0.0,"cost_value":0.0,"avg":0.0})
        if typ==0:
            qty=float(row["qty"]); cost=float(row["price"])
            r["qty"]+=qty; r["cost_value"]+=qty*cost
            r["avg"]=(r["cost_value"]/r["qty"]) if r["qty"] else 0.0
            spent += qty*cost
        else:
            qty=float(row["qty"]); unit=r["avg"]
            c=qty*unit
            sale_cogs[rid]=c
            r["sold"]+=qty; r["qty"]-=qty; r["cost_value"]-=c
            if r["qty"] > 0:
                r["avg"]=r["cost_value"]/r["qty"]
            else:
                r["avg"]=0.0; r["cost_value"]=0.0
            cogs += c; rev += qty*float(row["price"])
    other_exp=sum(float(x["amount"] or 0) for x in db.execute("select amount from expenditures"))
    d={k:[v["name"],v["unit"],v["qty"]+v["sold"],v["sold"],v["cost_value"],v["avg"],v["qty"]] for k,v in products.items()}
    return d,spent,rev,cogs,rev-cogs,other_exp,rev-cogs-other_exp,sale_cogs

def stock_at_sale_date(product, unit, sale_id, sale_date, sale_created):
    """Stock immediately before a particular sale, using chronological order."""
    qty=0.0
    for p in db.execute("select * from purchases where lower(product)=lower(?) AND lower(COALESCE(unit,'pcs'))=lower(?)",(product,unit)):
        if _date_key(p["date"],p["created"]) <= _date_key(sale_date,sale_created): qty += float(p["qty"])
    for s in db.execute("select * from sales where lower(product)=lower(?) AND lower(COALESCE(unit,'pcs'))=lower(?)",(product,unit)):
        if s["id"]==sale_id: continue
        if _date_key(s["date"],s["created"]) < _date_key(sale_date,sale_created): qty -= float(s["qty"])
    return qty

def _integrity_ok(path):
    """Return True only when SQLite reports an intact database."""
    try:
        con=sqlite3.connect(path)
        result=con.execute("PRAGMA integrity_check").fetchone()[0]
        con.close()
        return str(result).lower()=="ok"
    except Exception:
        return False

def backup(reason="automatic"):
    """Create a verified timestamped SQLite backup.

    The backup is written to a temporary file first, integrity-checked, then
    atomically renamed. This prevents a half-written backup from being treated
    as a valid restore point.
    """
    BACK.mkdir(exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target=BACK/f"inventory_{stamp}.db"
    tmp=BACK/f".inventory_{stamp}.tmp.db"
    try:
        # SQLite backup API is safer than copying a live database file.
        source=sqlite3.connect(DB)
        dest=sqlite3.connect(tmp)
        source.backup(dest)
        dest.close(); source.close()
        if not _integrity_ok(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError("Backup integrity check failed.")
        os.replace(tmp,target)
        fs=sorted(BACK.glob("inventory_*.db"),key=lambda x:x.stat().st_mtime,reverse=True)
        for f in fs[50:]:
            try: f.unlink()
            except OSError: pass
        return target
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        raise

# Startup safety backup (defined above, so this call is valid now).
try:
    backup("startup")
except Exception:
    pass


def _xlsx_write(path, sheets):
    """Write a standards-compliant XLSX using only the standard library.

    sheets: list of (title, headers, rows). Strings are written as inline
    strings; numbers as numeric cells. rId1 belongs to workbook.xml in
    _rels/.rels, so worksheet relationships start at rId2.
    """
    import zipfile as _zip
    from xml.sax.saxutils import escape

    def col(n):
        out=""; n+=1
        while n:
            n,rem=divmod(n-1,26)
            out=chr(65+rem)+out
        return out

    def sheet_xml(headers,rows):
        xml=[
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            '<sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetData>'
        ]
        for ri,row in enumerate([headers]+list(rows),1):
            xml.append(f'<row r="{ri}">')
            for ci,value in enumerate(row):
                ref=f"{col(ci)}{ri}"
                if value is None: value=""
                if isinstance(value,bool):
                    xml.append(f'<c r="{ref}" t="inlineStr"><is><t>{"TRUE" if value else "FALSE"}</t></is></c>')
                elif isinstance(value,(int,float)):
                    xml.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    text=escape(str(value))
                    xml.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
            xml.append("</row>")
        xml.append("</sheetData></worksheet>")
        return "".join(xml).encode("utf-8")

    ct=[
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    wb=[
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
    ]
    rel=[
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    ]
    for i,(title,headers,rows) in enumerate(sheets,1):
        rid=i+1
        wb.append(f'<sheet name="{escape(title)}" sheetId="{i}" r:id="rId{rid}"/>')
        ct.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        rel.append(
            f'<Relationship Id="rId{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
    wb.append("</sheets></workbook>")
    rel.append("</Relationships>")
    ct.append("</Types>")
    rootrels=(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    with _zip.ZipFile(path,"w",_zip.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml","".join(ct))
        zf.writestr("_rels/.rels",rootrels)
        zf.writestr("xl/workbook.xml","".join(wb))
        zf.writestr("xl/_rels/workbook.xml.rels","".join(rel))
        for i,(_,headers,rows) in enumerate(sheets,1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml",sheet_xml(headers,rows))



# ---------------- Multi-company authentication ----------------
import hashlib, secrets, getpass

AUTH_DB=APP/"users.db"

def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return salt, digest

def _verify_password(password, salt, digest):
    _, candidate = _hash_password(password, salt)
    return secrets.compare_digest(candidate, digest)

def _auth_conn():
    con=sqlite3.connect(AUTH_DB)
    con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS companies(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, db_path TEXT NOT NULL UNIQUE, created TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_salt TEXT NOT NULL,
        password_hash TEXT NOT NULL, company_id INTEGER NOT NULL, created TEXT NOT NULL,
        FOREIGN KEY(company_id) REFERENCES companies(id))""")
    con.commit()
    return con

def _db_tables(path):
    con=sqlite3.connect(path)
    rows=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    con.close()
    return [r[0] for r in rows]

def _prepare_company_db(path, source=None):
    path=Path(path)
    if path.exists(): return
    if source and Path(source).exists():
        shutil.copy2(source,path)
        con=sqlite3.connect(path)
        # Keep the accounting chart of accounts, but start every company with clean business data.
        for table in _db_tables(path):
            if table not in {"accounts"}:
                try: con.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError: pass
        try: con.execute("DELETE FROM sqlite_sequence")
        except sqlite3.OperationalError: pass
        con.commit(); con.close()
    else:
        # Create a fresh DB using the current application's schema initializer.
        con=sqlite3.connect(path); con.close()
        _initialize_company_database(path)

def _initialize_company_database(path):
    global db
    old=db
    old_path=DB
    try:
        # The application has already created the complete schema in the initial DB.
        # This function is only a fallback; copying the initial DB is preferred.
        con=sqlite3.connect(path)
        con.execute("CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,vendor TEXT,pan TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT,customer TEXT DEFAULT '',payment_status TEXT DEFAULT 'Cash',paid REAL DEFAULT 0,due_date TEXT DEFAULT '')")
        con.execute("CREATE TABLE IF NOT EXISTS expenditures(id INTEGER PRIMARY KEY,date TEXT,category TEXT,description TEXT,amount REAL,created TEXT)")
        con.commit(); con.close()
    finally:
        db=old

def _switch_database(db_path, company_name):
    global db, DB, BACK, EXP
    try: db.close()
    except Exception: pass
    DB=Path(db_path)
    BACK=DB.parent/"backups"; EXP=DB.parent/"exports"
    BACK.mkdir(exist_ok=True); EXP.mkdir(exist_ok=True)
    db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
    # Re-run the full schema so the new company's DB matches the startup state.
    # --- Core tables ---
    db.execute("""CREATE TABLE IF NOT EXISTS purchases(
id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,vendor TEXT,pan TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS sales(
id INTEGER PRIMARY KEY,date TEXT,invoice TEXT,product TEXT,qty REAL,unit TEXT DEFAULT 'pcs',price REAL,created TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS expenditures(
id INTEGER PRIMARY KEY,date TEXT,category TEXT,description TEXT,amount REAL,created TEXT)""")
    # --- Column migrations ---
    for table in ("purchases","sales","expenditures"):
        cols={r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if "bs_date" not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN bs_date TEXT")
    for table in ("purchases","sales"):
        cols={r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if "unit" not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN unit TEXT DEFAULT 'pcs'")
        db.execute(f"UPDATE {table} SET unit='pcs' WHERE unit IS NULL OR trim(unit)=''")
    # --- Sales credit tracking columns ---
    sale_cols={r["name"] for r in db.execute("PRAGMA table_info(sales)")}
    for col,definition in [("customer","TEXT DEFAULT ''"),("payment_status","TEXT DEFAULT 'Cash'"),
        ("paid","REAL DEFAULT 0"),("due_date","TEXT DEFAULT ''")]:
        if col not in sale_cols:
            db.execute(f"ALTER TABLE sales ADD COLUMN {col} {definition}")
    db.execute("UPDATE sales SET payment_status='Cash' WHERE payment_status IS NULL OR payment_status=''")
    db.execute("UPDATE sales SET paid=price*qty WHERE paid IS NULL OR (payment_status='Cash' AND paid=0)")
    # --- Validation triggers ---
    db.execute("""CREATE TRIGGER IF NOT EXISTS purchases_validate_insert BEFORE INSERT ON purchases BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS purchases_validate_update BEFORE UPDATE ON purchases BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS sales_validate_insert BEFORE INSERT ON sales BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS sales_validate_update BEFORE UPDATE ON sales BEGIN SELECT CASE WHEN NEW.qty<=0 THEN RAISE(ABORT,'Quantity must be greater than zero') WHEN NEW.price<0 THEN RAISE(ABORT,'Price cannot be negative') WHEN trim(NEW.product)='' THEN RAISE(ABORT,'Product is required') END; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS expenditures_validate_insert BEFORE INSERT ON expenditures BEGIN SELECT CASE WHEN NEW.amount<0 THEN RAISE(ABORT,'Amount cannot be negative') WHEN trim(NEW.category)='' THEN RAISE(ABORT,'Category is required') END; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS expenditures_validate_update BEFORE UPDATE ON expenditures BEGIN SELECT CASE WHEN NEW.amount<0 THEN RAISE(ABORT,'Amount cannot be negative') WHEN trim(NEW.category)='' THEN RAISE(ABORT,'Category is required') END; END""")
    # --- Accounting tables ---
    db.execute("""CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        account_type TEXT NOT NULL, parent_code TEXT DEFAULT '',
        opening_balance REAL DEFAULT 0, active INTEGER DEFAULT 1, created TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS journal_entries(
        id INTEGER PRIMARY KEY, entry_date TEXT NOT NULL, reference TEXT DEFAULT '',
        description TEXT DEFAULT '', source_type TEXT DEFAULT '',
        source_id INTEGER DEFAULT 0, created TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS journal_lines(
        id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL,
        account_code TEXT NOT NULL, debit REAL DEFAULT 0, credit REAL DEFAULT 0,
        memo TEXT DEFAULT '', FOREIGN KEY(journal_id) REFERENCES journal_entries(id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY, payment_date TEXT NOT NULL, party_type TEXT NOT NULL,
        party TEXT NOT NULL, amount REAL NOT NULL, method TEXT DEFAULT 'Cash',
        direction TEXT NOT NULL, reference TEXT DEFAULT '', note TEXT DEFAULT '',
        created TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS accounting_periods(
        id INTEGER PRIMARY KEY, period_name TEXT UNIQUE NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT DEFAULT 'Open')""")
    for code,name,typ,parent in [
        ("1000","Cash","Asset",""),("1010","Bank","Asset",""),("1020","Accounts Receivable","Asset",""),
        ("1100","Inventory","Asset",""),("2000","Accounts Payable","Liability",""),
        ("3000","Owner Equity","Equity",""),("4000","Sales Revenue","Income",""),
        ("4100","Other Income","Income",""),("5000","Cost of Goods Sold","Expense",""),
        ("6000","Operating Expenses","Expense","")]:
        db.execute("""INSERT OR IGNORE INTO accounts(code,name,account_type,parent_code,created)
                      VALUES(?,?,?,?,?)""",
                   (code,name,typ,parent,datetime.now().isoformat(timespec="seconds")))
    db.execute("CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_journal_account ON journal_lines(account_code)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date)")
    db.commit()
    return company_name

def _ensure_first_company():
    # Kept for backward compatibility; first-run setup is now handled explicitly
    # by the LoginWindow so no default password is silently created.
    _auth_conn().close()


class LoginWindow(tk.Tk):
    """Local company selector.

    This version intentionally has no username or password. A company is the
    identity/workspace on this device; each company has its own database.
    The legacy users table is kept by _auth_conn() for compatibility with
    databases created by earlier versions.
    """
    def __init__(self):
        super().__init__()
        self.result=None
        self.title("Smart Inventory — Select Company")
        self.geometry("600x640"); self.minsize(520,580); self.configure(bg="#f0edf3")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _companies(self):
        con=_auth_conn()
        rows=con.execute("SELECT id,name,db_path FROM companies ORDER BY lower(name)").fetchall()
        con.close()
        return rows

    def _build(self):
        outer=tk.Frame(self,bg="#f0edf3")
        outer.pack(fill="both",expand=True)
        # Gradient-like brand bar with stacked frames
        brand_top=tk.Frame(outer,bg="#1e1b24",height=60)
        brand_top.pack(fill="x"); brand_top.pack_propagate(False)
        brand_bot=tk.Frame(outer,bg="#302a33",height=60)
        brand_bot.pack(fill="x"); brand_bot.pack_propagate(False)
        tk.Label(brand_top,text="  ⬡  SMART INVENTORY",bg="#1e1b24",fg="white",
                 font=("Segoe UI",22,"bold")).pack(side="left",padx=36,pady=(14,0))
        tk.Label(brand_bot,text="    Business inventory & accounting",bg="#302a33",fg="#c8bfc9",
                 font=("Segoe UI",10)).pack(side="left",padx=72)

        card=tk.Frame(outer,bg="white",highlightbackground="#d8d0dc",highlightthickness=1)
        card.pack(fill="both",expand=True,padx=80,pady=36)

        companies=self._companies()
        first_run=not companies
        tk.Label(card,text=("Set up your business" if first_run else "Select your company"),
                 bg="white",fg="#1e1b24",font=("Segoe UI",22,"bold")).pack(anchor="w",padx=40,pady=(36,6))
        tk.Label(card,text=("Create a company to get started." if first_run else "Choose the business workspace you want to open."),
                 bg="white",fg="#756d78",font=("Segoe UI",10)).pack(anchor="w",padx=40,pady=(0,28))

        if first_run:
            info_frame=tk.Frame(card,bg="#f8f5fa",highlightbackground="#e8e0ec",highlightthickness=1)
            info_frame.pack(fill="x",padx=40,pady=(0,24))
            tk.Label(info_frame,text="  NO COMPANY YET",bg="#f8f5fa",fg="#8a828d",
                     font=("Segoe UI",9,"bold")).pack(anchor="w",padx=12,pady=(14,4))
            tk.Label(info_frame,text="  Create your first company below. No login credentials are required.",
                     bg="#f8f5fa",fg="#5f5863",wraplength=360,justify="left",font=("Segoe UI",10)).pack(anchor="w",padx=12,pady=(0,14))
        else:
            tk.Label(card,text="COMPANY",bg="white",fg="#554c58",
                     font=("Segoe UI",9,"bold")).pack(anchor="w",padx=40)
            self.company_var=tk.StringVar(value=companies[0]["name"])
            self.company_box=ttk.Combobox(card,textvariable=self.company_var,
                                          values=[r["name"] for r in companies],state="readonly",
                                          font=("Segoe UI",12))
            self.company_box.pack(fill="x",padx=40,pady=(8,24),ipady=7)
            self.company_box.bind("<Return>",lambda e:self.continue_company())
            tk.Button(card,text="CONTINUE  →",command=self.continue_company,bg="#c83d73",fg="white",
                      activebackground="#ad315f",activeforeground="white",bd=0,
                      font=("Segoe UI",11,"bold"),height=2,cursor="hand2").pack(fill="x",padx=40)

        sep=tk.Frame(card,bg="#eae4ee",height=1); sep.pack(fill="x",padx=40,pady=20)
        tk.Button(card,text="＋  Create New Company",command=self.create_company,bg="white",fg="#c83d73",
                  activebackground="#faf6f8",bd=0,font=("Segoe UI",10,"bold"),cursor="hand2",
                  padx=16,pady=8).pack(pady=(0,8))
        tk.Label(card,text="Each company has its own separate inventory, accounting, reports and business data.",
                 bg="white",fg="#8a828d",wraplength=400,font=("Segoe UI",9)).pack(padx=40,pady=(0,32))

    def continue_company(self):
        name=self.company_var.get().strip()
        if not name:
            messagebox.showwarning("Select Company","Select a company first.",parent=self); return
        con=_auth_conn()
        row=con.execute("SELECT db_path,name FROM companies WHERE lower(name)=lower(?)",(name,)).fetchone()
        con.close()
        if not row:
            messagebox.showerror("Company unavailable","That company could not be found.",parent=self); return
        self.result=(row["db_path"],row["name"],"Local user")
        self.destroy()

    def create_company(self):
        d=tk.Toplevel(self); d.title("Create New Company"); d.geometry("500x340"); d.minsize(460,300)
        d.configure(bg="white"); d.transient(self); d.grab_set()
        # Header bar
        hdr=tk.Frame(d,bg="#1e1b24",height=8); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(d,text="Create New Company",bg="white",fg="#1e1b24",
                 font=("Segoe UI",20,"bold")).pack(anchor="w",padx=38,pady=(24,4))
        tk.Label(d,text="A separate database will be created for this company. Only the name is required.",
                 bg="white",fg="#756d78",font=("Segoe UI",10),wraplength=400,justify="left").pack(anchor="w",padx=38,pady=(0,24))
        tk.Label(d,text="COMPANY NAME",bg="white",fg="#554c58",
                 font=("Segoe UI",9,"bold")).pack(anchor="w",padx=38)
        entry=tk.Entry(d,font=("Segoe UI",12),relief="flat",bg="#f8f6fa",insertbackground="#24202a",
                 highlightbackground="#d8d0dc",highlightthickness=1)
        entry.pack(fill="x",padx=38,pady=(8,24),ipady=8)

        def save():
            name=entry.get().strip()
            if not name:
                messagebox.showwarning("Create Company","Enter a company name.",parent=d); return
            con=_auth_conn()
            if con.execute("SELECT 1 FROM companies WHERE lower(name)=lower(?)",(name,)).fetchone():
                con.close(); messagebox.showerror("Create Company","That company already exists.",parent=d); return
            existing_count=con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            cid=con.execute("SELECT COALESCE(MAX(id),0)+1 FROM companies").fetchone()[0]
            if existing_count == 0:
                path=DB
            else:
                safe=re.sub(r"[^A-Za-z0-9_-]+","_",name).strip("_") or f"company_{cid}"
                path=APP/"companies"/f"{cid}_{safe}.db"; path.parent.mkdir(exist_ok=True)
                _prepare_company_db(path,DB)
            con.execute("INSERT INTO companies(name,db_path,created) VALUES(?,?,?)",
                        (name,str(path),datetime.now().isoformat(timespec="seconds")))
            con.commit(); con.close()
            d.destroy()
            self.result=(str(path),name,"Local user")
            self.destroy()

        btn_frame=tk.Frame(d,bg="white"); btn_frame.pack(fill="x",padx=38,pady=(8,0))
        tk.Button(btn_frame,text="CREATE COMPANY",command=save,bg="#c83d73",fg="white",
                  activebackground="#ad315f",activeforeground="white",bd=0,
                  font=("Segoe UI",10,"bold"),padx=20,pady=10,cursor="hand2").pack(side="left")
        tk.Button(btn_frame,text="Cancel",command=d.destroy,bg="#ede8ee",fg="#302a33",
                  activebackground="#e1d9e0",bd=0,font=("Segoe UI",10,"bold"),
                  padx=20,pady=10,cursor="hand2").pack(side="left",padx=10)
        entry.focus_set(); d.bind("<Return>",lambda e:save())

    def _cancel(self):
        self.result=None; self.destroy()


def launch():
    _ensure_first_company()
    login=LoginWindow(); login.mainloop()
    if not login.result: return
    db_path,company_name,local_user=login.result
    _switch_database(db_path,company_name)
    app=App(company_name=company_name,username=local_user)
    app.mainloop()

class App(tk.Tk):

    def download_excel_template(self):
        from tkinter import filedialog, messagebox
        path=filedialog.asksaveasfilename(title="Save Excel Template",defaultextension=".xlsx",filetypes=[("Excel","*.xlsx")])
        if not path: return
        sheets=[
            ("Purchases",["AD Date","B.S. Date","Invoice No.","Vendor Name","Vendor PAN","Product","Quantity","Unit","Unit Cost"],[]),
            ("Sales",["AD Date","B.S. Date","Invoice No.","Customer","Product","Quantity","Selling Price","Paid Amount","Payment Status","Due Date"],[]),
            ("Expenditures",["AD Date","B.S. Date","Category","Description","Amount"],[]),
            ("Opening Stock",["AD Date","B.S. Date","Product","Quantity","Unit","Unit Cost"],[]),
        ]
        try:
            _xlsx_write(path,sheets)
            messagebox.showinfo("Template created","Excel template saved successfully.")
        except Exception as exc:
            messagebox.showerror("Template failed","Could not create the Excel template.\n\n"+str(exc))

    def import_excel(self):
        """Import .xlsx files using only Python's standard library.
        Automatically detects Purchases, Sales, Expenditures, or Opening Stock
        from sheet headers and validates before writing to SQLite.
        """
        from tkinter import filedialog, messagebox

        path=filedialog.askopenfilename(
            title="Import Excel",
            filetypes=[("Excel Workbook (*.xlsx)","*.xlsx")]
        )
        if not path:
            return

        import zipfile as _zipfile
        import xml.etree.ElementTree as ET
        from datetime import datetime as _datetime, timedelta as _timedelta

        try:
            zf=_zipfile.ZipFile(path)
            shared=[]
            if "xl/sharedStrings.xml" in zf.namelist():
                root=ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in root.findall("m:si",ns):
                    shared.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

            wbroot=ET.fromstring(zf.read("xl/workbook.xml"))
            relroot=ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            ns_main="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            ns_rel="http://schemas.openxmlformats.org/package/2006/relationships"
            rels={}
            for rel in relroot:
                rels[rel.attrib.get("Id")]=rel.attrib.get("Target","")
            sheets=[]
            for sh in wbroot.find("{%s}sheets"%ns_main):
                name=sh.attrib.get("name","")
                rid=sh.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target=rels.get(rid,"")
                if target.startswith("/"): target=target[1:]
                elif not target.startswith("xl/"): target="xl/"+target
                sheets.append((name,target))

            def col_index(ref):
                letters=re.match(r"[A-Z]+",ref or "")
                if not letters: return 0
                n=0
                for ch in letters.group(0):
                    n=n*26+(ord(ch)-64)
                return n-1

            def read_sheet(target):
                root=ET.fromstring(zf.read(target))
                rows=[]
                for row in root.findall(".//{%s}row"%ns_main):
                    cells={}
                    for c in row.findall("{%s}c"%ns_main):
                        idx=col_index(c.attrib.get("r",""))
                        typ=c.attrib.get("t")
                        v=c.find("{%s}v"%ns_main)
                        val="" if v is None else (v.text or "")
                        if typ=="s":
                            try: val=shared[int(val)]
                            except Exception: pass
                        elif typ=="inlineStr":
                            val="".join(t.text or "" for t in c.iter("{%s}t"%ns_main))
                        elif typ=="b":
                            val="TRUE" if val=="1" else "FALSE"
                        cells[idx]=val
                    if cells:
                        maxidx=max(cells)
                        rows.append([cells.get(i,"") for i in range(maxidx+1)])
                return rows

            all_sheets=[]
            for name,target in sheets:
                rows=read_sheet(target)
                if rows:
                    all_sheets.append((name,rows))
            zf.close()
        except Exception as exc:
            messagebox.showerror("Excel import failed",
                                 "Could not read this Excel workbook.\n\n"
                                 + str(exc))
            return

        if not all_sheets:
            messagebox.showwarning("Excel import","The workbook contains no readable data.")
            return

        def norm(x):
            return re.sub(r"[^a-z0-9]+","",str(x or "").strip().lower())

        aliases={
            "ad_date":["addate","date","transactiondate"],
            "bs_date":["bsdate","nepalidate","bikram sambatdate"],
            "invoice":["invoiceno","invoice","invoicenumber"],
            "vendor":["vendorname","vendor","supplier","suppliername"],
            "pan":["vendorpan","pan","panno","pannumber"],
            "product":["product","productname","item","itemname"],
            "quantity":["quantity","qty"],
            "unit":["unit","uom","unitofmeasure","measure"],
            "unit_cost":["unitcost","purchaseprice","costprice","price"],
            "selling_price":["sellingprice","saleprice","unitprice","price"],
            "customer":["customer","customername","buyer","buyername"],
            "paid":["paidamount","paid","amountpaid"],
            "payment_status":["paymentstatus","status"],
            "due_date":["duedate"],
            "category":["category","expensecategory"],
            "description":["description","details","particulars"],
            "amount":["amount","expenseamount","expenditure"],
        }
        def key_for(header):
            h=norm(header)
            for k,vals in aliases.items():
                if h in {norm(v) for v in vals}: return k
            return None

        def parse_number(v):
            if v is None or str(v).strip()=="":
                raise ValueError("missing number")
            return float(str(v).replace(",","").replace("Rs.","").replace("rs.","").strip())

        def excel_date(v):
            if v is None or str(v).strip()=="":
                return ""
            text=str(v).strip()
            # Excel serial date
            try:
                n=float(text)
                if 1 <= n <= 100000:
                    return str(_datetime(1899,12,30)+_timedelta(days=n))[:10]
            except Exception:
                pass
            # Already ISO date or common date formats.
            for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%m/%d/%Y"):
                try:
                    return _datetime.strptime(text,fmt).strftime("%Y-%m-%d")
                except Exception:
                    pass
            return text

        detected=[]
        for name,rows in all_sheets:
            headers=rows[0]
            keys={key_for(h) for h in headers}
            keys.discard(None)
            kind=None
            if {"category","amount"} <= keys and "product" not in keys:
                kind="Expenditures"
            elif {"product","quantity","unit_cost"} <= keys and "vendor" not in keys and "selling_price" not in keys:
                kind="Opening Stock"
            elif {"product","quantity"} <= keys and ("vendor" in keys or "unit_cost" in keys):
                kind="Purchases"
            elif {"product","quantity"} <= keys and ("selling_price" in keys or "customer" in keys):
                kind="Sales"
            if kind:
                detected.append((kind,name,rows,headers))

        if not detected:
            messagebox.showerror(
                "Excel import",
                "I couldn't identify the data type from the column headings.\n\n"
                "Use the Excel Template button to create a correctly formatted workbook."
            )
            return

        # Import every recognized sheet in one operation.
        preview=[]
        prepared=[]
        for kind,name,rows,headers in detected:
            mapping={key_for(h):i for i,h in enumerate(headers) if key_for(h)}
            for row_no,row in enumerate(rows[1:],2):
                if not any(str(x).strip() for x in row): continue
                # Helper to extract cell value immediately (avoids closure bug)
                def _get_cell(r, m):
                    def cell(k,default=""):
                        i=m.get(k)
                        return r[i] if i is not None and i<len(r) else default
                    return cell
                cell=_get_cell(row, mapping)
                try:
                    if kind=="Expenditures":
                        category=str(cell("category")).strip()
                        amount=parse_number(cell("amount"))
                        if not category or amount<0: raise ValueError("category required; amount >= 0")
                        # Extract all needed values now to avoid late-binding closure issues
                        prepared.append((kind,name,row_no,
                            str(cell("ad_date") or "").strip(),
                            str(cell("bs_date") or "").strip(),
                            category,amount,
                            str(cell("description") or "").strip()))
                    else:
                        product=str(cell("product")).strip()
                        qty=parse_number(cell("quantity"))
                        price=parse_number(cell("unit_cost" if kind!="Sales" else "selling_price"))
                        unit=str(cell("unit") or "pcs").strip() or "pcs"
                        if not product or qty<=0 or price<0:
                            raise ValueError("product required; quantity > 0; price >= 0")
                        # Extract all needed values now to avoid late-binding closure issues
                        prepared.append((kind,name,row_no,
                            str(cell("ad_date") or "").strip(),
                            str(cell("bs_date") or "").strip(),
                            product,qty,price,unit,
                            str(cell("invoice") or "").strip(),
                            str(cell("vendor") or "").strip() if kind!="Sales" else "",
                            str(cell("pan") or "").strip() if kind=="Purchases" else "",
                            str(cell("customer") or "").strip() if kind=="Sales" else "",
                            str(cell("payment_status") or "Cash").strip() if kind=="Sales" else "",
                            str(cell("paid") or "").strip() if kind=="Sales" else "",
                            str(cell("due_date") or "").strip() if kind=="Sales" else ""))
                except Exception as exc:
                    messagebox.showerror("Excel validation failed",
                                         f"{name}, row {row_no}: {exc}")
                    return

        if not prepared:
            messagebox.showwarning("Excel import","No data rows were found.")
            return

        for item in prepared[:8]:
            preview.append(f"{item[0]} / {item[1]} / row {item[2]}")
        if len(prepared)>8: preview.append(f"... and {len(prepared)-8} more rows")

        if not messagebox.askyesno(
            "Confirm Excel import",
            f"Detected {len(detected)} data sheet(s) and {len(prepared)} row(s).\n\n"
            + "\n".join(preview) + "\n\nImport them?"
        ):
            return

        try:
            backup()
        except Exception:
            pass

        try:
            db.execute("BEGIN")
            for item in prepared:
                kind=item[0]; name=item[1]; row_no=item[2]
                if kind=="Expenditures":
                    ad_date_val,bs_date_val,category,amount,description=item[3],item[4],item[5],item[6],item[7]
                else:
                    ad_date_val,bs_date_val,product,qty,price,unit=item[3],item[4],item[5],item[6],item[7],item[8]
                    invoice,vendor,pan,customer,payment_status,paid,due_date=item[9],item[10],item[11],item[12],item[13],item[14],item[15]
                ad=excel_date(ad_date_val)
                bs=bs_date_val
                if ad and not bs:
                    bs=ad_to_bs(ad)
                elif bs and not ad:
                    ad=bs_to_ad(bs)
                if not ad or not bs:
                    raise ValueError(f"{name}, row {row_no}: valid AD/B.S. date required")

                if kind=="Purchases":
                    db.execute("""INSERT INTO purchases
                        (date,bs_date,invoice,vendor,pan,product,qty,unit,price,created)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (ad,bs,invoice,vendor,pan,product,qty,unit,price,
                         _datetime.now().isoformat(timespec="seconds")))
                elif kind=="Sales":
                    paid_val=0
                    try: paid_val=parse_number(paid) if str(paid).strip() else 0
                    except Exception: paid_val=0
                    db.execute("""INSERT INTO sales
                        (date,bs_date,invoice,product,qty,unit,price,created,customer,payment_status,paid,due_date)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (ad,bs,invoice,product,qty,unit,price,
                         _datetime.now().isoformat(timespec="seconds"),
                         customer,payment_status,paid_val,due_date))
                elif kind=="Expenditures":
                    db.execute("""INSERT INTO expenditures
                        (date,bs_date,category,description,amount,created)
                        VALUES (?,?,?,?,?,?)""",
                        (ad,bs,category,description,amount,
                         _datetime.now().isoformat(timespec="seconds")))
                elif kind=="Opening Stock":
                    db.execute("""INSERT INTO purchases
                        (date,bs_date,invoice,vendor,pan,product,qty,unit,price,created)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (ad,bs,"OPENING STOCK","","",product,qty,unit,price,
                         _datetime.now().isoformat(timespec="seconds")))
            db.commit()
            self.dashboard()
            messagebox.showinfo("Import complete",
                                f"Successfully imported {len(prepared)} row(s).")
        except Exception as exc:
            db.rollback()
            messagebox.showerror("Import failed",
                                 "Nothing was imported because the transaction was rolled back.\n\n"
                                 + str(exc))

    def _delete_selected(self, tree, table, title):
        from tkinter import messagebox
        sel=tree.selection()
        if not sel:
            messagebox.showwarning("Delete",f"Select a {title.lower()} record first."); return
        values=tree.item(sel[0],"values")
        tags=tree.item(sel[0],"tags") or ()
        candidates=[tree.item(sel[0],"text"),tags[0] if tags else None,sel[0],values[0] if values else None]
        record_id=None
        for cand in candidates:
            try: record_id=int(cand); break
            except (TypeError,ValueError): continue
        if record_id is None:
            messagebox.showerror("Delete","Could not determine the record ID."); return
        if not messagebox.askyesno("Confirm Delete",f"Delete this {title.lower()} record?\n\n"+" | ".join(map(str,values[:5]))): return
        try: backup("before_delete")
        except Exception: pass
        try:
            db.execute("BEGIN")
            cur=db.execute(f"DELETE FROM {table} WHERE id=?",(record_id,))
            if cur.rowcount==0: db.rollback(); messagebox.showwarning("Delete","Record not found."); return
            db.commit()
            self._sync_legacy_accounting()
            {"purchases":self.purchases,"sales":self.sales,"expenditures":self.expenditures}.get(table,self.dashboard)()
            messagebox.showinfo("Deleted",f"{title} deleted successfully.")
        except Exception as exc:
            try: db.rollback()
            except Exception: pass
            messagebox.showerror("Delete failed",str(exc))

    def delete_selected_purchase(self):
        tree=getattr(self,"purchase_tree",None) or getattr(self,"purchases_tree",None)
        if tree: self._delete_selected(tree,"purchases","Purchase")

    def delete_selected_sale(self):
        tree=getattr(self,"sales_tree",None) or getattr(self,"sale_tree",None)
        if tree: self._delete_selected(tree,"sales","Sale")

    def delete_selected_expenditure(self):
        tree=getattr(self,"exp_tree",None)
        if tree: self._delete_selected(tree,"expenditures","Expenditure")

    def _safe_backup(self, reason="automatic"):
        """Best-effort backup that never blocks or masks a successful save."""
        try: backup(reason)
        except Exception: pass

    def _manual_backup(self):
        try:
            path=backup("manual")
            messagebox.showinfo("Backup",f"Verified backup created:\n{path}")
        except Exception as exc:
            messagebox.showerror("Backup failed",str(exc))


    def _safe_table_exists(self, name):
        return db.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone() is not None

    def _ensure_upgrade_tables(self):
        db.execute("""create table if not exists products_master(
            id integer primary key, sku text unique, barcode text unique, name text not null,
            category text, brand text, unit text default 'pcs', reorder_level real default 0,
            selling_price real default 0, active integer default 1)""")
        db.execute("""create table if not exists customers(
            id integer primary key, name text not null, phone text, address text, pan text,
            credit_limit real default 0, notes text)""")
        db.execute("""create table if not exists suppliers(
            id integer primary key, name text not null, phone text, address text, pan text,
            payment_terms text, notes text)""")
        db.execute("""create table if not exists warehouses(
            id integer primary key, name text unique not null, address text, active integer default 1)""")
        db.execute("""create table if not exists stock_adjustments(
            id integer primary key, date text, bs_date text, product text, quantity real,
            reason text, note text, created text default current_timestamp)""")
        db.execute("""create table if not exists purchase_orders(
            id integer primary key, order_no text unique, date text, bs_date text,
            supplier text, status text default 'Draft', total real default 0, notes text)""")
        db.execute("""create table if not exists sales_returns(
            id integer primary key, date text, bs_date text, invoice text, product text,
            quantity real, amount real default 0, reason text, created text default current_timestamp)""")
        db.execute("""create table if not exists purchase_returns(
            id integer primary key, date text, bs_date text, invoice text, product text,
            quantity real, amount real default 0, reason text, created text default current_timestamp)""")
        db.commit()

    def business_center(self):
        """Open the expanded business-management workspace."""
        import tkinter as tk
        from tkinter import ttk, messagebox
        self._ensure_upgrade_tables()

        win=tk.Toplevel(self)
        win.title("Business Center")
        win.geometry("1100x720")
        win.minsize(900,600)
        win.configure(bg="#f7f7fb")

        style=ttk.Style(win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("BC.TFrame", background="#f7f7fb")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("BC.Title.TLabel", background="#f7f7fb", foreground="#272331",
                        font=("Segoe UI",20,"bold"))
        style.configure("BC.Sub.TLabel", background="#f7f7fb", foreground="#777180",
                        font=("Segoe UI",10))
        style.configure("BC.TButton", padding=(14,9), font=("Segoe UI",10,"bold"))

        top=ttk.Frame(win,style="BC.TFrame"); top.pack(fill="x",padx=24,pady=(20,10))
        ttk.Label(top,text="Business Center",style="BC.Title.TLabel").pack(anchor="w")
        ttk.Label(top,text="Products, customers, suppliers, warehouses, alerts and operational tools",
                  style="BC.Sub.TLabel").pack(anchor="w",pady=(3,0))

        nb=ttk.Notebook(win); nb.pack(fill="both",expand=True,padx=20,pady=10)

        def tab(title):
            f=ttk.Frame(nb,style="Card.TFrame"); nb.add(f,text=title); return f

        # Products
        ptab=tab("Products & Reorder")
        cols=("id","sku","barcode","name","category","unit","reorder","price")
        pt=ttk.Treeview(ptab,columns=cols,show="headings")
        for c,w in zip(cols,(50,120,130,220,130,80,90,100)):
            pt.heading(c,text=c.replace("_"," ").title()); pt.column(c,width=w)
        pt.pack(fill="both",expand=True,padx=12,pady=12)
        def load_products():
            pt.delete(*pt.get_children())
            for r in db.execute("select id,sku,barcode,name,category,unit,reorder_level,selling_price from products_master order by name"):
                pt.insert("", "end", iid=str(r[0]), values=r)
        load_products()
        pf=ttk.Frame(ptab,style="Card.TFrame"); pf.pack(fill="x",padx=12,pady=(0,12))
        def add_product():
            d=tk.Toplevel(win); d.title("Add Product"); d.geometry("420x430")
            fields=["SKU","Barcode","Name *","Category","Brand","Unit","Reorder Level","Selling Price"]
            ent={}
            for i,label in enumerate(fields):
                ttk.Label(d,text=label).pack(anchor="w",padx=18,pady=(10,2))
                e=ttk.Entry(d); e.pack(fill="x",padx=18); ent[label]=e
            ent["Unit"].insert(0,"pcs")
            def save():
                if not ent["Name *"].get().strip():
                    messagebox.showwarning("Product","Product name is required.",parent=d); return
                try:
                    db.execute("""insert into products_master(sku,barcode,name,category,brand,unit,reorder_level,selling_price)
                                  values(?,?,?,?,?,?,?,?)""",
                               (ent["SKU"].get() or None,ent["Barcode"].get() or None,ent["Name *"].get().strip(),
                                ent["Category"].get(),ent["Brand"].get(),ent["Unit"].get() or "pcs",
                                float(ent["Reorder Level"].get() or 0),float(ent["Selling Price"].get() or 0)))
                    db.commit(); load_products(); d.destroy()
                except Exception as e: messagebox.showerror("Product",str(e),parent=d)
            ttk.Button(d,text="Save Product",command=save,style="BC.TButton").pack(pady=18)
        ttk.Button(pf,text="Add Product",command=add_product,style="BC.TButton").pack(side="left",padx=5)
        def low_stock():
            rows=[]
            for r in db.execute("select name,reorder_level from products_master where active=1 and reorder_level>0"):
                stock=sum(float(x[0] or 0) for x in db.execute("select qty from purchases where product=?",(r[0],)))-sum(float(x[0] or 0) for x in db.execute("select qty from sales where product=?",(r[0],)))
                if stock<=float(r[1]): rows.append((r[0],stock,r[1]))
            messagebox.showinfo("Low Stock", "\n".join(f"{a}: {b:g} / reorder {c:g}" for a,b,c in rows) if rows else "No low-stock products.",parent=win)
        ttk.Button(pf,text="Low Stock Check",command=low_stock,style="BC.TButton").pack(side="left",padx=5)

        # Parties
        ctab=tab("Customers")
        ctree=ttk.Treeview(ctab,columns=("id","name","phone","pan","credit"),show="headings")
        for c,w in zip(("id","name","phone","pan","credit"),(50,260,160,140,120)):
            ctree.heading(c,text=c.title()); ctree.column(c,width=w)
        ctree.pack(fill="both",expand=True,padx=12,pady=12)
        def load_customers():
            ctree.delete(*ctree.get_children())
            for r in db.execute("select id,name,phone,pan,credit_limit from customers order by name"): ctree.insert("", "end",iid=str(r[0]),values=r)
        load_customers()
        cf=ttk.Frame(ctab,style="Card.TFrame"); cf.pack(fill="x",padx=12,pady=(0,12))
        def add_customer():
            d=tk.Toplevel(win); d.title("Add Customer"); d.geometry("400x330")
            labels=["Name *","Phone","Address","PAN","Credit Limit"]
            es={}
            for lab in labels:
                ttk.Label(d,text=lab).pack(anchor="w",padx=18,pady=(10,2)); e=ttk.Entry(d); e.pack(fill="x",padx=18); es[lab]=e
            def save():
                if not es["Name *"].get().strip(): return
                db.execute("insert into customers(name,phone,address,pan,credit_limit) values(?,?,?,?,?)",
                           (es["Name *"].get(),es["Phone"].get(),es["Address"].get(),es["PAN"].get(),float(es["Credit Limit"].get() or 0)))
                db.commit(); load_customers(); d.destroy()
            ttk.Button(d,text="Save Customer",command=save,style="BC.TButton").pack(pady=18)
        ttk.Button(cf,text="Add Customer",command=add_customer,style="BC.TButton").pack(side="left",padx=5)

        # Suppliers
        stab=tab("Suppliers")
        st=ttk.Treeview(stab,columns=("id","name","phone","pan","terms"),show="headings")
        for c,w in zip(("id","name","phone","pan","terms"),(50,260,160,140,160)):
            st.heading(c,text=c.title()); st.column(c,width=w)
        st.pack(fill="both",expand=True,padx=12,pady=12)
        def load_suppliers():
            st.delete(*st.get_children())
            for r in db.execute("select id,name,phone,pan,payment_terms from suppliers order by name"): st.insert("", "end",iid=str(r[0]),values=r)
        load_suppliers()
        sf=ttk.Frame(stab,style="Card.TFrame"); sf.pack(fill="x",padx=12,pady=(0,12))
        def add_supplier():
            d=tk.Toplevel(win); d.title("Add Supplier"); d.geometry("400x360")
            labels=["Name *","Phone","Address","PAN","Payment Terms","Notes"]; es={}
            for lab in labels:
                ttk.Label(d,text=lab).pack(anchor="w",padx=18,pady=(8,2)); e=ttk.Entry(d); e.pack(fill="x",padx=18); es[lab]=e
            def save():
                if not es["Name *"].get().strip(): return
                db.execute("insert into suppliers(name,phone,address,pan,payment_terms,notes) values(?,?,?,?,?,?)",
                           (es["Name *"].get(),es["Phone"].get(),es["Address"].get(),es["PAN"].get(),es["Payment Terms"].get(),es["Notes"].get()))
                db.commit(); load_suppliers(); d.destroy()
            ttk.Button(d,text="Save Supplier",command=save,style="BC.TButton").pack(pady=16)
        ttk.Button(sf,text="Add Supplier",command=add_supplier,style="BC.TButton").pack(side="left",padx=5)

        # Warehouses
        wtab=tab("Warehouses")
        wt=ttk.Treeview(wtab,columns=("id","name","address","active"),show="headings")
        for c,w in zip(("id","name","address","active"),(50,300,350,100)):
            wt.heading(c,text=c.title()); wt.column(c,width=w)
        wt.pack(fill="both",expand=True,padx=12,pady=12)
        for r in db.execute("select id,name,address,active from warehouses order by name"): wt.insert("", "end",iid=str(r[0]),values=r)
        wf=ttk.Frame(wtab,style="Card.TFrame"); wf.pack(fill="x",padx=12,pady=(0,12))
        def add_warehouse():
            d=tk.Toplevel(win); d.title("Add Warehouse"); d.geometry("380x240")
            ttk.Label(d,text="Warehouse Name *").pack(anchor="w",padx=18,pady=(18,2)); n=ttk.Entry(d); n.pack(fill="x",padx=18)
            ttk.Label(d,text="Address").pack(anchor="w",padx=18,pady=(12,2)); a=ttk.Entry(d); a.pack(fill="x",padx=18)
            def save():
                if n.get().strip():
                    db.execute("insert into warehouses(name,address) values(?,?)",(n.get().strip(),a.get()))
                    db.commit(); wt.insert("", "end",values=(db.execute("select last_insert_rowid()").fetchone()[0],n.get(),a.get(),1)); d.destroy()
            ttk.Button(d,text="Save Warehouse",command=save,style="BC.TButton").pack(pady=18)
        ttk.Button(wf,text="Add Warehouse",command=add_warehouse,style="BC.TButton").pack(side="left",padx=5)

        # Reports / analytics
        rtab=tab("Reports & Insights")
        rtxt=tk.Text(rtab,wrap="word",font=("Segoe UI",10),bg="#ffffff",fg="#2d2836",relief="flat",padx=20,pady=20)
        rtxt.pack(fill="both",expand=True,padx=12,pady=12)
        def refresh_report():
            rtxt.delete("1.0","end")
            try:
                revenue=sum(float(q or 0)*float(p or 0) for q,p in db.execute("select qty,price from sales"))
                purchases=sum(float(q or 0)*float(p or 0) for q,p in db.execute("select qty,price from purchases"))
                expenses=sum(float(a or 0) for (a,) in db.execute("select amount from expenditures"))
                units_bought=sum(float(q or 0) for (q,) in db.execute("select qty from purchases"))
                units_sold=sum(float(q or 0) for (q,) in db.execute("select qty from sales"))
                rtxt.insert("end",
                    "BUSINESS SNAPSHOT\n\n"
                    f"Sales Revenue: NPR {revenue:,.2f}\n"
                    f"Purchase Value: NPR {purchases:,.2f}\n"
                    f"Recorded Expenditures: NPR {expenses:,.2f}\n"
                    f"Units Purchased: {units_bought:,.2f}\n"
                    f"Units Sold: {units_sold:,.2f}\n\n"
                    "Recommended controls now available:\n"
                    "• Product/SKU/barcode master\n"
                    "• Reorder levels and low-stock check\n"
                    "• Customer and supplier records\n"
                    "• Warehouse records\n"
                    "• Stock adjustments / returns tables\n"
                    "• Purchase-order foundation\n"
                    "• Reporting foundation\n")
            except Exception as e: rtxt.insert("end",f"Report error: {e}")
        ttk.Button(rtab,text="Refresh Insights",command=refresh_report,style="BC.TButton").pack(anchor="e",padx=12,pady=(0,8))
        refresh_report()

        # Returns / operations
        otab=tab("Operations")
        ttk.Label(otab,text="Operational tools",font=("Segoe UI",14,"bold"),background="#ffffff").pack(anchor="w",padx=20,pady=20)
        ttk.Label(otab,text="The database now supports purchase returns, sales returns, stock adjustments and purchase orders. "
                  "These can be connected to dedicated workflows next without changing existing records.",
                  wraplength=850,background="#ffffff",foreground="#6e6876").pack(anchor="w",padx=20)
        def show_counts():
            rows=[]
            for table in ("purchases","sales","expenditures","purchase_orders","sales_returns","purchase_returns","stock_adjustments"):
                try: rows.append(f"{table.replace('_',' ').title()}: {db.execute(f'select count(*) from {table}').fetchone()[0]}")
                except Exception: pass
            messagebox.showinfo("Database Overview","\n".join(rows),parent=win)
        ttk.Button(otab,text="Database Overview",command=show_counts,style="BC.TButton").pack(anchor="w",padx=20,pady=20)

    def financial_center(self):
        self.clear(); self.heading("Financial Center","Detailed money calculations and cash flow analysis")
        d,purchases,sales,cogs,profit,expenses,net_profit,sale_cogs=calc()
        money_used=purchases+expenses; money_received=sales; cash_flow=money_received-money_used
        inventory_value=sum(max(0,float(r[6]))*float(r[5]) for r in d.values())
        # Row 1: Primary financial metrics
        row1=tk.Frame(self.body,bg="#f4f2f7"); row1.pack(fill="x",pady=(0,8))
        for title,val,col in [("Total Bought",purchases,"#1e1b24"),("Total Sold",sales,"#18794e"),("Net Cash Flow",cash_flow,"#18794e" if cash_flow>=0 else "#a83255"),("Net Profit",net_profit,"#18794e" if net_profit>=0 else "#a83255")]:
            self._metric_card(row1,title,M(val),col)
        # Row 2: Secondary metrics
        row2=tk.Frame(self.body,bg="#f4f2f7"); row2.pack(fill="x",pady=(0,8))
        for title,val,col in [("COGS",cogs,"#6f4b3e"),("Gross Profit",profit,"#18794e" if profit>=0 else "#a83255"),("Other Expenses",expenses,"#8f244e"),("Inventory Value",inventory_value,"#3f6f8e")]:
            self._metric_card(row2,title,M(val),col)
        # Calculation breakdown
        calcbox=self._make_card(self.body); calcbox.pack(fill="both",expand=True,pady=(0,8))
        tk.Label(calcbox,text="MONEY CALCULATION",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).pack(anchor="w",padx=20,pady=(16,10))
        lines=[("Sales / money received",sales),("Less: Cost of Goods Sold",-cogs),("Gross profit",profit),("Less: Other expenditures",-expenses),("Net profit",net_profit),("Total purchase money used",purchases),("Other expenditure money used",expenses),("Total money used",money_used),("Net cash flow",cash_flow)]
        for i,(label,val) in enumerate(lines):
            bg="#faf8fc" if i%2==0 else "white"
            row_f=tk.Frame(calcbox,bg=bg); row_f.pack(fill="x",padx=20)
            tk.Label(row_f,text=label,bg=bg,fg="#3b3540",font=("Segoe UI",10,"bold")).pack(side="left",pady=8)
            tk.Label(row_f,text=M(val),bg=bg,fg="#1e1b24",font=("Segoe UI",11,"bold")).pack(side="right",padx=20,pady=8)
        tk.Label(calcbox,text="Current inventory value is based on the stock remaining after purchases and sales.",bg="white",fg="#756d78",font=("Segoe UI",9)).pack(anchor="w",padx=20,pady=(8,16))

    def _safe_column_exists(self, table, column):
        try:
            return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})"))
        except Exception:
            return False


    def professional_dashboard(self):
        import tkinter as tk
        from tkinter import ttk, messagebox
        from datetime import datetime, timedelta

        win=tk.Toplevel(self)
        win.title("Business Center")
        win.geometry("1180x800")
        win.minsize(980,680)
        win.configure(bg="#f6f7fb")

        style=ttk.Style(win)
        try: style.theme_use("clam")
        except Exception: pass
        style.configure("Dash.TFrame",background="#f6f7fb")
        style.configure("Dash.Card",background="#ffffff")
        style.configure("Dash.Title",background="#f6f7fb",foreground="#26212b",font=("Segoe UI",24,"bold"))
        style.configure("Dash.Sub",background="#f6f7fb",foreground="#77717c",font=("Segoe UI",10))
        style.configure("Dash.Value",background="#ffffff",foreground="#26212b",font=("Segoe UI",19,"bold"))
        style.configure("Dash.Label",background="#ffffff",foreground="#746d78",font=("Segoe UI",9))
        style.configure("Dash.TButton",padding=(13,8),font=("Segoe UI",10,"bold"))

        ttk.Label(win,text="Business Center",style="Dash.Title").pack(anchor="w",padx=26,pady=(22,2))
        ttk.Label(win,text="One place for stock, money, profit and business health",style="Dash.Sub").pack(anchor="w",padx=26)

        controls=ttk.Frame(win,style="Dash.TFrame"); controls.pack(fill="x",padx=26,pady=14)
        ttk.Label(controls,text="Period:").pack(side="left")
        period=tk.StringVar(value="All Time")
        cb=ttk.Combobox(controls,textvariable=period,state="readonly",
                        values=["All Time","Today","This Week","This Month","This Year"],width=16)
        cb.pack(side="left",padx=8)

        cards=ttk.Frame(win,style="Dash.TFrame"); cards.pack(fill="x",padx=20)
        for c in range(4): cards.columnconfigure(c,weight=1)
        card={}
        metrics=[
            ("sales","Total Sold"),("purchases","Total Bought"),("expenses","Expenses"),
            ("profit","Net Profit"),("stock","Stock Value"),("cash","Net Cash Flow"),
            ("low","Low Stock"),("expiry","Expiry Alerts")
        ]
        for i,(key,label) in enumerate(metrics):
            r,c=divmod(i,4)
            f=ttk.Frame(cards,style="Dash.Card"); f.grid(row=r,column=c,sticky="nsew",padx=6,pady=6)
            ttk.Label(f,text=label,style="Dash.Label").pack(anchor="w",padx=14,pady=(12,0))
            v=ttk.Label(f,text="0",style="Dash.Value"); v.pack(anchor="w",padx=14,pady=(4,12))
            card[key]=v

        info=ttk.Frame(win,style="Dash.Card"); info.pack(fill="both",expand=True,padx=26,pady=16)
        text=tk.Text(info,wrap="word",font=("Segoe UI",10),bg="#fff",fg="#312b34",
                     relief="flat",padx=20,pady=18)
        text.pack(fill="both",expand=True)

        def period_bounds():
            now=datetime.now(); p=period.get()
            end=now.strftime("%Y-%m-%d")
            if p=="Today": return end,end
            if p=="This Week": return (now-timedelta(days=now.weekday())).strftime("%Y-%m-%d"),end
            if p=="This Month": return now.strftime("%Y-%m-01"),end
            if p=="This Year": return now.strftime("%Y-01-01"),end
            return None,None

        def qsum(table,expr,start,end):
            try:
                if start:
                    q=f"SELECT COALESCE(SUM({expr}),0) FROM {table} WHERE date(date)>=date(?) AND date(date)<=date(?)"
                    return float(db.execute(q,(start,end)).fetchone()[0] or 0)
                return float(db.execute(f"SELECT COALESCE(SUM({expr}),0) FROM {table}").fetchone()[0] or 0)
            except Exception:
                return 0.0

        def refresh(*_):
            start,end=period_bounds()
            sales_expr="revenue" if self._safe_column_exists("sales","revenue") else "qty*price"
            sales=qsum("sales",sales_expr,start,end)
            purchases=qsum("purchases","qty*price",start,end)
            expenses=qsum("expenditures","amount",start,end)
            cogs=qsum("sales","cogs",start,end) if self._safe_column_exists("sales","cogs") else 0
            profit=sales-cogs-expenses
            paid=qsum("sales","paid",start,end) if self._safe_column_exists("sales","paid") else sales
            cash=paid-purchases-expenses

            low=0
            try:
                # Support common reorder-level column names without breaking older DBs.
                cols=[r[1] for r in db.execute("PRAGMA table_info(products)")]
                if "reorder_level" in cols and "stock" in cols:
                    low=db.execute("SELECT COUNT(*) FROM products WHERE stock<=reorder_level").fetchone()[0]
            except Exception: pass

            expiry=0
            for table in ("purchases","products"):
                try:
                    cols=[r[1] for r in db.execute(f"PRAGMA table_info({table})")]
                    if "expiry_date" in cols:
                        expiry += db.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE expiry_date IS NOT NULL AND date(expiry_date)<=date(?)",
                            ((datetime.now()+timedelta(days=90)).strftime("%Y-%m-%d"),)
                        ).fetchone()[0]
                except Exception: pass

            # Current inventory value from weighted-average purchase cost.
            stock_value=0
            try:
                items={}
                for product,qty,price in db.execute("SELECT product,qty,price FROM purchases"):
                    x=items.setdefault(str(product),[0.0,0.0,0.0]); q=float(qty or 0)
                    x[0]+=q; x[1]+=q*float(price or 0)
                for product,qty in db.execute("SELECT product,qty FROM sales"):
                    items.setdefault(str(product),[0.0,0.0,0.0])[2]+=float(qty or 0)
                for q,cost,sold in items.values():
                    remaining=max(0,q-sold); stock_value += remaining*(cost/q if q else 0)
            except Exception: pass

            card["sales"].configure(text=f"NPR {sales:,.0f}")
            card["purchases"].configure(text=f"NPR {purchases:,.0f}")
            card["expenses"].configure(text=f"NPR {expenses:,.0f}")
            card["profit"].configure(text=f"NPR {profit:,.0f}")
            card["stock"].configure(text=f"NPR {stock_value:,.0f}")
            card["cash"].configure(text=f"NPR {cash:,.0f}")
            card["low"].configure(text=str(low))
            card["expiry"].configure(text=str(expiry))

            text.delete("1.0","end")
            text.insert("end","BUSINESS HEALTH SUMMARY\n\n")
            text.insert("end",f"Sales revenue                 NPR {sales:,.2f}\n")
            text.insert("end",f"Purchases                     NPR {purchases:,.2f}\n")
            text.insert("end",f"Operating expenditures        NPR {expenses:,.2f}\n")
            text.insert("end",f"Cost of Goods Sold            NPR {cogs:,.2f}\n")
            text.insert("end",f"Net profit                    NPR {profit:,.2f}\n")
            text.insert("end",f"Net cash flow                 NPR {cash:,.2f}\n")
            text.insert("end",f"Current inventory value       NPR {stock_value:,.2f}\n\n")
            text.insert("end",f"Low-stock alerts              {low}\n")
            text.insert("end",f"Near-expiry/expiry alerts    {expiry}\n\n")
            text.insert("end","Use the period selector to change the financial window. "
                       "The dashboard remains compatible with older databases where optional columns do not exist.")

        cb.bind("<<ComboboxSelected>>",refresh)
        ttk.Button(controls,text="Refresh",command=refresh,style="Dash.TButton").pack(side="left",padx=5)
        refresh()


    def product_control_center(self):
        import tkinter as tk
        from tkinter import ttk, messagebox
        win=tk.Toplevel(self); win.title("Product Control Center"); win.geometry("1000x650")
        win.configure(bg="#f7f7fb")
        ttk.Label(win,text="Product Control Center",font=("Segoe UI",22,"bold")).pack(anchor="w",padx=24,pady=(20,4))
        ttk.Label(win,text="Search products and review stock, batch and expiry information").pack(anchor="w",padx=24)

        top=ttk.Frame(win); top.pack(fill="x",padx=24,pady=12)
        q=tk.StringVar()
        ttk.Entry(top,textvariable=q,width=35).pack(side="left")
        tree=ttk.Treeview(win,columns=("product","stock","batch","expiry"),show="headings")
        for col,title,w in [("product","Product",300),("stock","Stock",100),("batch","Batch",180),("expiry","Expiry",160)]:
            tree.heading(col,text=title); tree.column(col,width=w)
        tree.pack(fill="both",expand=True,padx=24,pady=8)

        def load(*_):
            tree.delete(*tree.get_children())
            try:
                cols=[r[1] for r in db.execute("PRAGMA table_info(purchases)")]
                has_batch="batch_no" in cols; has_exp="expiry_date" in cols
                select="product,qty"
                if has_batch: select+=",batch_no"
                if has_exp: select+=",expiry_date"
                rows=db.execute(f"SELECT {select} FROM purchases ORDER BY product").fetchall()
                for row in rows:
                    product=row[0]; stock=row[1]; pos=2
                    batch=row[pos] if has_batch else ""; pos+=1 if has_batch else 0
                    expiry=row[pos] if has_exp else ""
                    if q.get().strip().lower() not in str(product).lower(): continue
                    tree.insert("", "end", values=(product,stock,batch,expiry))
            except Exception as e:
                messagebox.showerror("Product Control Center",str(e))
        q.trace_add("write",load); ttk.Button(top,text="Refresh",command=load).pack(side="left",padx=8)
        load()


    def _quantity_input(self, parent, variable=None, width=12):
        """Professional quantity control: numeric validation, +/- buttons, no negatives."""
        import tkinter as tk
        if variable is None:
            variable=tk.StringVar(value="1")
        frame=tk.Frame(parent,bg=parent.cget("bg"))
        def clean(*_):
            raw=variable.get().strip()
            if raw=="":
                return
            try:
                v=float(raw)
                if v<0: variable.set("0")
                elif v.is_integer(): variable.set(str(int(v)))
            except Exception:
                variable.set(re.sub(r"[^0-9.]", "", raw))
        def change(delta):
            try:
                v=float(variable.get() or 0)
            except Exception:
                v=0
            v=max(0, v+delta)
            variable.set(str(int(v)) if v.is_integer() else f"{v:g}")
        entry=tk.Entry(frame,textvariable=variable,width=width,justify="center",
                       font=("Segoe UI",11),relief="solid",bd=1)
        entry.pack(side="left",ipady=5)
        tk.Button(frame,text="−",command=lambda:change(-1),width=3,
                  bg="#eeeeee",bd=0).pack(side="left",padx=(3,1))
        tk.Button(frame,text="+",command=lambda:change(1),width=3,
                  bg="#eeeeee",bd=0).pack(side="left",padx=(1,0))
        variable.trace_add("write",clean)
        return frame, variable, entry

    def _valid_quantity(self, value):
        try:
            q=float(str(value).strip())
            return q>0 and q<100000000
        except Exception:
            return False

    def _attach_quantity(self, parent, e, row, initial="1"):
        """Replace the plain qty entry from self.form() with the +/- quantity control.

        e["qty"] still behaves like an Entry (get/insert/delete), so existing
        validation and prefill code keeps working unchanged.
        """
        old=e.get("qty")
        if old is not None:
            try: old.destroy()
            except Exception: pass
        frame,variable,entry=self._quantity_input(parent, tk.StringVar(value=initial))
        frame.grid(row=row,column=1,sticky="w",padx=20,pady=5)
        e["qty"]=entry
        e["qty_var"]=variable


    def data_protection_center(self):
        from tkinter import filedialog, messagebox
        win=tk.Toplevel(self)
        win.title("Data Protection Center")
        win.geometry("820x600")
        win.configure(bg="#f7f5f8")

        tk.Label(win,text="Data Protection Center",bg="#f7f5f8",
                 fg="#29242b",font=("Segoe UI",22,"bold")).pack(anchor="w",padx=26,pady=(22,3))
        tk.Label(win,text="Protect, verify and restore your business data",
                 bg="#f7f5f8",fg="#756d78",font=("Segoe UI",10)).pack(anchor="w",padx=26)

        status=tk.Frame(win,bg="white"); status.pack(fill="x",padx=26,pady=18)
        integrity=tk.Label(status,text="Checking database integrity...",
                           bg="white",fg="#756d78",font=("Segoe UI",13,"bold"))
        integrity.pack(anchor="w",padx=18,pady=(16,4))
        details=tk.Label(status,text="",bg="white",fg="#756d78",justify="left")
        details.pack(anchor="w",padx=18,pady=(0,16))

        def refresh():
            ok=_integrity_ok(DB)
            integrity.configure(
                text="✓ Database integrity: OK" if ok else "⚠ Database integrity problem detected",
                fg="#18794e" if ok else "#a83255")
            backups=sorted(BACK.glob("inventory_*.db"),key=lambda x:x.stat().st_mtime,reverse=True)
            details.configure(text=f"Database: {DB}\nVerified backups: {len(backups)}\nBackup folder: {BACK}\n"
                                  f"Latest backup: {backups[0].name if backups else 'None'}")

        actions=tk.Frame(win,bg="#f7f5f8"); actions.pack(fill="x",padx=26)
        def make_backup():
            try:
                path=backup("manual")
                messagebox.showinfo("Backup complete",f"Verified backup created:\n{path}")
                refresh()
            except Exception as exc:
                messagebox.showerror("Backup failed",str(exc))
        def restore():
            global db
            path=filedialog.askopenfilename(initialdir=BACK,
                                            title="Select verified backup",
                                            filetypes=[("SQLite backup","*.db")])
            if not path:return
            if not _integrity_ok(path):
                messagebox.showerror("Restore blocked","The selected backup failed the SQLite integrity check.")
                return
            if not messagebox.askyesno("Restore backup",
                "A verified backup of the current database will be created before restoring.\n\nContinue?"):
                return
            try:
                backup("before_restore")
                db.close()
                shutil.copy2(path,DB)
                if not _integrity_ok(DB):
                    raise RuntimeError("Restored database failed integrity verification.")
                db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
                self.dashboard()
                refresh()
                messagebox.showinfo("Restore complete","The verified backup was restored successfully.")
            except Exception as exc:
                messagebox.showerror("Restore failed",str(exc))
        tk.Button(actions,text="Create Verified Backup",command=make_backup,bg="#2c252b",fg="white",
                  bd=0,padx=16,pady=9).pack(side="left",padx=4)
        tk.Button(actions,text="Restore Backup",command=restore,bg="#c33d70",fg="white",
                  bd=0,padx=16,pady=9).pack(side="left",padx=4)
        tk.Button(actions,text="Refresh Check",command=refresh,bg="#eeeeee",fg="#29242b",
                  bd=0,padx=16,pady=9).pack(side="left",padx=4)

        log=tk.Text(win,height=13,bg="white",fg="#332d38",relief="flat",font=("Segoe UI",9),
                    padx=16,pady=14)
        log.pack(fill="both",expand=True,padx=26,pady=18)
        log.insert("end","DATA SAFETY POLICY\n\n"
                  "• Backups are verified with SQLite integrity_check.\n"
                  "• Backups are created before destructive operations.\n"
                  "• Up to 50 timestamped restore points are retained.\n"
                  "• Failed writes are rolled back where transaction handling is used.\n"
                  "• Restores are blocked when the selected backup is corrupt.\n")
        refresh()


    def _account_balance(self, code, start=None, end=None):
        """Signed account balance: assets/expenses debit-positive, others credit-positive."""
        try:
            params=[code]
            where="jl.account_code=?"
            if start: where+=" AND je.entry_date>=?"; params.append(start)
            if end: where+=" AND je.entry_date<=?"; params.append(end)
            row=db.execute(f"""SELECT COALESCE(SUM(jl.debit),0),COALESCE(SUM(jl.credit),0)
                               FROM journal_lines jl JOIN journal_entries je ON je.id=jl.journal_id
                               WHERE {where}""",params).fetchone()
            debit,credit=float(row[0]),float(row[1])
            typ=db.execute("SELECT account_type FROM accounts WHERE code=?",(code,)).fetchone()
            typ=typ[0] if typ else "Asset"
            return debit-credit if typ in ("Asset","Expense") else credit-debit
        except Exception:
            return 0.0

    def _post_journal(self, date, reference, description, source_type, source_id, lines):
        """Atomically post a balanced double-entry journal entry."""
        total_debit=sum(float(x[1]) for x in lines)
        total_credit=sum(float(x[2]) for x in lines)
        if abs(total_debit-total_credit)>0.005:
            raise ValueError("Unbalanced journal entry.")
        db.execute("BEGIN")
        try:
            cur=db.execute("""INSERT INTO journal_entries
                (entry_date,reference,description,source_type,source_id,created)
                VALUES(?,?,?,?,?,?)""",
                (date,reference,description,source_type,source_id,datetime.now().isoformat(timespec="seconds")))
            jid=cur.lastrowid
            for code,debit,credit,memo in lines:
                if float(debit)<0 or float(credit)<0 or (float(debit)>0 and float(credit)>0):
                    raise ValueError("Each journal line must have either debit or credit.")
                if not db.execute("SELECT 1 FROM accounts WHERE code=? AND active=1",(code,)).fetchone():
                    raise ValueError(f"Unknown/inactive account: {code}")
                db.execute("""INSERT INTO journal_lines(journal_id,account_code,debit,credit,memo)
                              VALUES(?,?,?,?,?)""",(jid,code,float(debit),float(credit),memo))
            db.commit()
            return jid
        except Exception:
            db.rollback()
            raise

    def accounting_center(self):
        from tkinter import ttk, messagebox
        win=tk.Toplevel(self); win.title("Accounting Center"); win.geometry("1120x760")
        win.configure(bg="#f7f5f8")
        tk.Label(win,text="Accounting Center",bg="#f7f5f8",fg="#29242b",
                 font=("Segoe UI",23,"bold")).pack(anchor="w",padx=26,pady=(20,2))
        tk.Label(win,text="Double-entry ledger, balances, profit & loss, balance sheet and cash position",
                 bg="#f7f5f8",fg="#756d78").pack(anchor="w",padx=26)

        top=tk.Frame(win,bg="#f7f5f8"); top.pack(fill="x",padx=26,pady=15)
        start=tk.StringVar(value=datetime.now().strftime("%Y-01-01"))
        end=tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        tk.Label(top,text="From",bg="#f7f5f8").pack(side="left")
        tk.Entry(top,textvariable=start,width=12).pack(side="left",padx=5)
        tk.Label(top,text="To",bg="#f7f5f8").pack(side="left")
        tk.Entry(top,textvariable=end,width=12).pack(side="left",padx=5)

        body=tk.Frame(win,bg="white"); body.pack(fill="both",expand=True,padx=26,pady=5)
        txt=tk.Text(body,bg="white",fg="#332d38",relief="flat",font=("Consolas",10),
                    padx=20,pady=18); txt.pack(fill="both",expand=True)

        def report():
            txt.delete("1.0","end")
            a={r["code"]:r["name"] for r in db.execute("SELECT code,name FROM accounts WHERE active=1 ORDER BY code")}
            vals={code:self._account_balance(code,start.get().strip() or None,end.get().strip() or None) for code in a}
            revenue=vals.get("4000",0)+vals.get("4100",0)
            cogs=vals.get("5000",0); opex=vals.get("6000",0)
            net=revenue-cogs-opex
            assets=sum(vals.get(x,0) for x in ("1000","1010","1020","1100"))
            liabilities=vals.get("2000",0); equity=vals.get("3000",0)
            txt.insert("end","PROFIT & LOSS\n"+"="*72+"\n")
            txt.insert("end",f"Revenue                         NPR {revenue:>14,.2f}\n")
            txt.insert("end",f"Cost of Goods Sold              NPR {cogs:>14,.2f}\n")
            txt.insert("end",f"Operating Expenses              NPR {opex:>14,.2f}\n")
            txt.insert("end",f"NET PROFIT                      NPR {net:>14,.2f}\n\n")
            txt.insert("end","BALANCE SHEET\n"+"="*72+"\n")
            txt.insert("end",f"Assets                          NPR {assets:>14,.2f}\n")
            txt.insert("end",f"Liabilities                     NPR {liabilities:>14,.2f}\n")
            txt.insert("end",f"Equity                          NPR {equity:>14,.2f}\n")
            txt.insert("end",f"Net profit                      NPR {net:>14,.2f}\n")
            txt.insert("end",f"Liabilities + Equity            NPR {liabilities+equity+net:>14,.2f}\n\n")
            txt.insert("end","ACCOUNT BALANCES\n"+"="*72+"\n")
            for code,name in a.items():
                txt.insert("end",f"{code}  {name:<28} NPR {vals[code]:>14,.2f}\n")

        def add_payment():
            d=tk.Toplevel(win); d.title("Record Payment"); d.geometry("480x430")
            fields={}
            for label,default in [("Date",datetime.now().strftime("%Y-%m-%d")),("Party",""),
                                  ("Amount",""),("Method","Cash"),("Direction","Received"),
                                  ("Reference",""),("Note","")]:
                tk.Label(d,text=label).pack(anchor="w",padx=20,pady=(10,2))
                if label in ("Method","Direction"):
                    var=tk.StringVar(value=default)
                    w=ttk.Combobox(d,textvariable=var,state="readonly",
                                   values=(["Cash","Bank","QR","Cheque","Other"] if label=="Method"
                                           else ["Received","Paid"]))
                else:
                    var=tk.StringVar(value=default); w=tk.Entry(d,textvariable=var)
                w.pack(fill="x",padx=20); fields[label]=var
            def save():
                try:
                    amount=float(fields["Amount"].get())
                    if amount<=0: raise ValueError("Amount must be greater than zero.")
                    db.execute("""INSERT INTO payments(payment_date,party_type,party,amount,method,direction,reference,note,created)
                                  VALUES(?,?,?,?,?,?,?,?,?)""",
                               (fields["Date"].get(),"Party",fields["Party"].get().strip(),amount,
                                fields["Method"].get(),fields["Direction"].get(),fields["Reference"].get(),
                                fields["Note"].get(),datetime.now().isoformat(timespec="seconds")))
                    db.commit()
                    d.destroy(); report()
                except Exception as ex:
                    db.rollback(); messagebox.showerror("Payment failed",str(ex))
            tk.Button(d,text="Save Payment",command=save,bg="#2c252b",fg="white",bd=0,padx=16,pady=8).pack(pady=18)
        tk.Button(top,text="Refresh Reports",command=report,bg="#2c252b",fg="white",bd=0,padx=14,pady=8).pack(side="left",padx=5)
        tk.Button(top,text="Record Payment",command=add_payment,bg="#18794e",fg="white",bd=0,padx=14,pady=8).pack(side="left",padx=5)
        report()


    def _sync_legacy_accounting(self):
        """Reconcile system-generated journals with the current transaction tables.

        Purchase/sale/expense records are the source of truth. Rebuilding only the
        system-generated journals prevents edits/deletes from leaving stale ledger
        entries and posts chronological weighted-average COGS for every sale.
        Manual journal entries are never touched.
        """
        try:
            _, _, _, _, _, _, _, sale_cogs = calc()
            db.execute("BEGIN")
            db.execute("DELETE FROM journal_lines WHERE journal_id IN (SELECT id FROM journal_entries WHERE source_type IN ('purchase','sale','expense'))")
            db.execute("DELETE FROM journal_entries WHERE source_type IN ('purchase','sale','expense')")

            def post(date_value, reference, description, source_type, source_id, lines):
                debit=sum(float(x[1]) for x in lines)
                credit=sum(float(x[2]) for x in lines)
                if abs(debit-credit)>0.005:
                    raise ValueError(f"Unbalanced {source_type} journal")
                cur=db.execute("""INSERT INTO journal_entries
                    (entry_date,reference,description,source_type,source_id,created)
                    VALUES(?,?,?,?,?,?)""",
                    (date_value,reference,description,source_type,source_id,datetime.now().isoformat(timespec="seconds")))
                jid=cur.lastrowid
                for code,d,c,memo in lines:
                    if d < 0 or c < 0 or (d > 0 and c > 0):
                        raise ValueError("Invalid journal line")
                    if not db.execute("SELECT 1 FROM accounts WHERE code=? AND active=1",(code,)).fetchone():
                        raise ValueError(f"Unknown/inactive account: {code}")
                    db.execute("INSERT INTO journal_lines(journal_id,account_code,debit,credit,memo) VALUES(?,?,?,?,?)",
                                (jid,code,float(d),float(c),memo))

            for p in db.execute("SELECT id,date,invoice,qty,price,product FROM purchases ORDER BY date,id"):
                amount=max(0.0,float(p["qty"] or 0))*max(0.0,float(p["price"] or 0))
                if amount:
                    post(p["date"],p["invoice"] or "",f"Purchase: {p['product']}","purchase",p["id"],
                         [("1100",amount,0,"Inventory"),("2000",0,amount,"Supplier payable")])

            for row in db.execute("SELECT id,date,invoice,qty,price,product FROM sales ORDER BY date,id"):
                revenue=max(0.0,float(row["qty"] or 0))*max(0.0,float(row["price"] or 0))
                cogs=max(0.0,float(sale_cogs.get(row["id"],0.0)))
                if revenue or cogs:
                    post(row["date"],row["invoice"] or "",f"Sale: {row['product']}","sale",row["id"],
                         [("1000",revenue,0,"Cash/receivable"),("4000",0,revenue,"Sales revenue"),
                          ("5000",cogs,0,"Cost of goods sold"),("1100",0,cogs,"Inventory")])

            for e in db.execute("SELECT id,date,category,description,amount FROM expenditures ORDER BY date,id"):
                amount=max(0.0,float(e["amount"] or 0))
                if amount:
                    post(e["date"],"",f"Expense: {e['category']} {e['description'] or ''}","expense",e["id"],
                         [("6000",amount,0,e["category"]),("1000",0,amount,"Cash")])
            db.commit()
        except Exception:
            try: db.rollback()
            except Exception: pass
            raise

    def __init__(self, company_name="My Company", username="admin"):
        super().__init__()
        self.company_name=company_name; self.username=username
        self._ensure_upgrade_tables(); self._sync_legacy_accounting()
        self.title(f"Smart Inventory — {company_name}"); self.geometry("1360x860"); self.minsize(1100,700)
        self.configure(bg="#f4f2f7")
        self.style=ttk.Style(); self.style.theme_use("clam")
        self.style.configure("Treeview",rowheight=36,font=("Segoe UI",9),background="#ffffff",fieldbackground="#ffffff",borderwidth=0,relief="flat",padding=(4,2))
        self.style.configure("Treeview.Heading",font=("Segoe UI",9,"bold"),padding=(12,10),background="#eef0f5",foreground="#35313a",relief="flat")
        self.style.map("Treeview",background=[("selected","#eadcf0")],foreground=[("selected","#2b2430")])
        self.style.configure("Primary.TButton",font=("Segoe UI",9,"bold"),padding=(14,9),background="#c83d73",foreground="#ffffff",borderwidth=0)
        self.style.map("Primary.TButton",background=[("active","#ad315f")])
        self.style.configure("Success.TButton",font=("Segoe UI",9,"bold"),padding=(14,9),background="#18794e",foreground="#ffffff",borderwidth=0)
        self.style.map("Success.TButton",background=[("active","#12613f")])
        self.style.configure("Neutral.TButton",font=("Segoe UI",9,"bold"),padding=(14,9),background="#ede8ee",foreground="#302a33",borderwidth=0)
        self.style.map("Neutral.TButton",background=[("active","#e1d9e0")])
        self._build_main_layout()
        self.dashboard()
        self.protocol("WM_DELETE_WINDOW",self.close)

    def _build_main_layout(self):
        # Top header bar
        self.header_bar=tk.Frame(self,bg="#1e1b24",height=65)
        self.header_bar.pack(fill="x"); self.header_bar.pack_propagate(False)
        tk.Label(self.header_bar,text="⬡  SMART INVENTORY",bg="#1e1b24",fg="white",
                 font=("Segoe UI",16,"bold")).pack(side="left",padx=(22,16))
        # Search in header
        self.search_var=tk.StringVar()
        sf=tk.Frame(self.header_bar,bg="#1e1b24"); sf.pack(side="left",padx=8)
        self.search_entry=tk.Entry(sf,textvariable=self.search_var,width=30,relief="flat",
                                    font=("Segoe UI",10),fg="#999",bg="#2e2935",insertbackground="white",
                                    highlightbackground="#3a3340",highlightthickness=1)
        se=self.search_entry
        se.insert(0,"Search products, invoices, vendors...")
        se.pack(side="left",ipady=6,padx=4)
        se.bind("<FocusIn>",lambda _: self._clear_search_placeholder())
        se.bind("<FocusOut>",lambda _: self._restore_search_placeholder())
        se.bind("<Return>",lambda _ : self.search_all())
        tk.Button(sf,text="Search",command=self.search_all,bg="#c83d73",fg="white",
                  activebackground="#ad315f",activeforeground="white",bd=0,
                  font=("Segoe UI",9,"bold"),padx=14,pady=6,cursor="hand2").pack(side="left",padx=6)
        # Quick company switcher on right of header - refined UI
        self.company_switch_frame=tk.Frame(self.header_bar,bg="#1e1b24")
        self.company_switch_frame.pack(side="right",padx=(8,18))
        
        self.company_btn=tk.Button(self.company_switch_frame,
                                   text=f"◉  {self.company_name}  ▾",
                                   command=self._toggle_company_menu,
                                   bg="#2d2633",fg="#e8e4e8",
                                   activebackground="#3d3645",activeforeground="#ffffff",
                                   bd=0,font=("Segoe UI",10,"bold"),
                                   padx=14,pady=6,cursor="hand2",
                                   highlightthickness=1,
                                   highlightbackground="#4a4355",
                                   highlightcolor="#c83d73")
        self.company_btn.pack(side="left")
        
        # Store reference to company menu popup
        self._company_menu=None
        self._menu_open=False

        # Workspace area
        workspace=tk.Frame(self,bg="#f4f2f7")
        workspace.pack(fill="both",expand=True)
        # Sidebar
        self.sidebar=tk.Frame(workspace,bg="#1e1b24",width=230)
        self.sidebar.pack(side="left",fill="y"); self.sidebar.pack_propagate(False)
        self._build_sidebar()
        # Content area
        content=tk.Frame(workspace,bg="#f4f2f7")
        content.pack(side="left",fill="both",expand=True)
        self.body_shell=tk.Frame(content,bg="#f4f2f7")
        self.body_shell.pack(fill="both",expand=True,padx=22,pady=18)
        self.body_canvas=tk.Canvas(self.body_shell,bg="#f4f2f7",highlightthickness=0,bd=0)
        self.body_vscroll=ttk.Scrollbar(self.body_shell,orient="vertical",command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=self.body_vscroll.set)
        self.body_vscroll.pack(side="right",fill="y"); self.body_canvas.pack(side="left",fill="both",expand=True)
        self.body=tk.Frame(self.body_canvas,bg="#f4f2f7")
        self._body_window=self.body_canvas.create_window((0,0),window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda e:self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all")))
        self.body_canvas.bind("<Configure>",lambda e:self.body_canvas.itemconfigure(self._body_window,width=max(e.width,1)))
        self.body_canvas.bind_all("<MouseWheel>",self._body_mousewheel)

    def _build_sidebar(self):
        tk.Label(self.sidebar,text="SMART",bg="#1e1b24",fg="white",
                 font=("Segoe UI",18,"bold")).pack(anchor="w",padx=24,pady=(26,0))
        tk.Label(self.sidebar,text="INVENTORY  ·  BUSINESS",bg="#1e1b24",fg="#7a7080",
                 font=("Segoe UI",8,"bold")).pack(anchor="w",padx=25,pady=(2,28))
        nav=[("Dashboard",self.dashboard),("Purchases",self.purchases),("Sales",self.sales),
             ("Inventory",self.inventory),("Expenditure",self.expenditures),
             ("Financial Center",self.financial_center),("Reports",self.reports),
             ("Data Protection",self.data_protection_center)]
        self.nav_buttons={}
        for name,cmd in nav:
            b=tk.Button(self.sidebar,text="  "+name,command=lambda c=cmd,n=name:self._navigate(c,n),
                        anchor="w",bg="#1e1b24",fg="#c8bfc9",activebackground="#c83d73",
                        activeforeground="white",bd=0,highlightthickness=0,
                        font=("Segoe UI",10,"bold"),padx=18,pady=12,cursor="hand2")
            b.pack(fill="x",padx=8,pady=1); self.nav_buttons[name]=b
        # Active indicator frame
        self.nav_indicator=tk.Frame(self.sidebar,bg="#c83d73",width=4)
        # Bottom section
        tk.Frame(self.sidebar,bg="#3a3340",height=1).pack(fill="x",padx=18,pady=18)
        user=tk.Frame(self.sidebar,bg="#2a2530")
        user.pack(side="bottom",fill="x",padx=10,pady=12)
        tk.Label(user,text="ACTIVE COMPANY",bg="#2a2530",fg="#7a7080",
                 font=("Segoe UI",7,"bold")).pack(anchor="w",padx=14,pady=(12,2))
        tk.Label(user,text=self.company_name,bg="#2a2530",fg="white",
                 font=("Segoe UI",10,"bold")).pack(anchor="w",padx=14)
        tk.Label(user,text=f"{self.username}",bg="#2a2530",fg="#8a828d",
                 font=("Segoe UI",8)).pack(anchor="w",padx=14,pady=(0,12))
        self._set_active_nav("Dashboard")

    def _set_active_nav(self,name):
        for n,b in self.nav_buttons.items():
            if n==name:
                b.configure(bg="#c83d73",fg="white")
            else:
                b.configure(bg="#1e1b24",fg="#c8bfc9")

    def _navigate(self,cmd,name):
        self._set_active_nav(name)
        cmd()
    def _body_mousewheel(self,event):
        try:
            if self.body_canvas.winfo_exists():
                self.body_canvas.yview_scroll(int(-event.delta/120), "units")
        except Exception:
            pass

    def _body_shiftwheel(self,event):
        try:
            if self.body_canvas.winfo_exists():
                self.body_canvas.xview_scroll(int(-event.delta/120), "units")
        except Exception:
            pass

    def _clear_search_placeholder(self):
        if self.search_entry.get() == "Search products, invoices, vendors...":
            self.search_entry.delete(0, "end"); self.search_entry.configure(fg="white")

    def _restore_search_placeholder(self):
        if not self.search_entry.get().strip():
            self.search_entry.insert(0, "Search products, invoices, vendors..."); self.search_entry.configure(fg="#999")

    def clear(self):
        for w in self.body.winfo_children(): w.destroy()
        def reset_scroll():
            try:
                self.update_idletasks()
                self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all"))
                self.body_canvas.yview_moveto(0.0)
            except Exception: pass
        self.after_idle(reset_scroll)
        self.after(40, reset_scroll)

    def heading(self,t,s=""):
        tk.Label(self.body,text=t,bg="#f4f2f7",font=("Segoe UI",22,"bold"),fg="#1e1b24").pack(anchor="w",pady=(0,4))
        if s: tk.Label(self.body,text=s,bg="#f4f2f7",fg="#756d78",font=("Segoe UI",10)).pack(anchor="w",pady=(0,16))

    def _make_card(self,parent,**kw):
        """Create a white card frame with subtle border."""
        bg=kw.pop("bg","white")
        f=tk.Frame(parent,bg=bg,highlightbackground="#e0d8e4",highlightthickness=1)
        return f

    def _metric_card(self,parent,title,value,color="#1e1b24"):
        """Create a metric card: title + big value."""
        card=self._make_card(parent)
        card.pack(side="left",fill="x",expand=True,padx=5,pady=5)
        tk.Label(card,text=title.upper(),bg="white",fg="#756d78",font=("Segoe UI",8,"bold")).pack(anchor="w",padx=16,pady=(14,3))
        tk.Label(card,text=value,bg="white",fg=color,font=("Segoe UI",18,"bold")).pack(anchor="w",padx=16,pady=(0,14))
        return card

    def _action_button(self,parent,text,command,color="#c83d73"):
        """Styled action button."""
        return tk.Button(parent,text=text,command=command,bg=color,fg="white",
                         activebackground=color,activeforeground="white",bd=0,
                         font=("Segoe UI",9,"bold"),padx=16,pady=9,cursor="hand2")

    def tree(self,parent,cols,rows):
        f=self._make_card(parent)
        f.pack(fill="both",expand=True,padx=5,pady=10)
        tr=ttk.Treeview(f,columns=cols,show="headings")
        tr.tag_configure("even",background="#faf8fc")
        tr.tag_configure("odd",background="#ffffff")
        for c in cols: tr.heading(c,text=c); tr.column(c,width=130,minwidth=80)
        tr.pack(side="top",fill="both",expand=True)
        scy=ttk.Scrollbar(f,orient="vertical",command=tr.yview); scy.pack(side="right",fill="y")
        scx=ttk.Scrollbar(f,orient="horizontal",command=tr.xview); scx.pack(side="bottom",fill="x")
        tr.configure(yscrollcommand=scy.set,xscrollcommand=scx.set)
        for i,r in enumerate(rows):
            tag="even" if i%2==0 else "odd"
            tr.insert("", "end",values=r,tags=(tag,))
        return tr
    def dashboard(self):
        self.clear(); self.heading("Dashboard","Business overview at a glance")
        d,sp,rev,cog,prof,other_exp,net_profit,sale_cogs=calc()
        # Row 1: Primary metrics
        row1=tk.Frame(self.body,bg="#f4f2f7"); row1.pack(fill="x",pady=(0,8))
        for a,b,col in [("Purchases",M(sp),"#1e1b24"),("Sales",M(rev),"#18794e"),("Net Profit",M(net_profit),"#18794e" if net_profit>=0 else "#a83255")]:
            self._metric_card(row1,a,b,col)
        # Row 2: Secondary metrics
        row2=tk.Frame(self.body,bg="#f4f2f7"); row2.pack(fill="x",pady=(0,12))
        for a,b,col in [("Cost of Goods Sold",M(cog),"#6f4b3e"),("Other Expenses",M(other_exp),"#8f244e"),("Gross Profit",M(prof),"#18794e" if prof>=0 else "#a83255")]:
            self._metric_card(row2,a,b,col)
        # Quick actions
        actions_card=self._make_card(self.body)
        actions_card.pack(fill="x",pady=(0,12))
        tk.Label(actions_card,text="QUICK ACTIONS",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).pack(anchor="w",padx=18,pady=(14,8))
        af=tk.Frame(actions_card,bg="white"); af.pack(fill="x",padx=18,pady=(0,14))
        for text,cmd,color in [("New Purchase",self.purchases,"#c83d73"),("New Sale",self.sales,"#18794e"),("View Reports",self.reports,"#3f6f8e"),("Export Excel",self.export_xlsx,"#6b5b73")]:
            self._action_button(af,text,cmd,color).pack(side="left",padx=4)
        # Stock table
        stock_card=self._make_card(self.body)
        stock_card.pack(fill="both",expand=True,pady=(0,8))
        tk.Label(stock_card,text="CURRENT STOCK",bg="white",fg="#1e1b24",font=("Segoe UI",14,"bold")).pack(anchor="w",padx=18,pady=(14,8))
        rows=[(r[0],r[1],Q(r[2]),Q(r[3]),Q(r[6]),M(r[5]),M(max(0,r[6])*r[5])) for r in d.values()]
        box_inner=tk.Frame(stock_card,bg="white"); box_inner.pack(fill="both",expand=True,padx=12,pady=(0,12))
        self.tree(box_inner,["Product","Unit","Purchased","Sold","Stock","Avg Cost","Stock Value"],rows)
        # Low stock alert
        low=[r for r in d.values() if r[6] <= 5]
        if low:
            alert=tk.Frame(self.body,bg="#fff8f0",highlightbackground="#f0d090",highlightthickness=1)
            alert.pack(fill="x",pady=4)
            tk.Label(alert,text="  ⚠  Low stock: " + ", ".join(f"{r[0]} [{r[1]}] ({Q(r[6])})" for r in low[:8]),
                     bg="#fff8f0",fg="#8a5b00",anchor="w",font=("Segoe UI",10),padx=14,pady=12).pack(fill="x")
        # Financial chart
        chart_card=self._make_card(self.body)
        chart_card.pack(fill="x",pady=(8,4))
        tk.Label(chart_card,text="FINANCIAL SNAPSHOT",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).pack(anchor="w",padx=18,pady=(14,8))
        chart=tk.Canvas(chart_card,height=160,bg="white",highlightthickness=0); chart.pack(fill="x",padx=18,pady=(0,18))
        vals=[("Revenue",rev,"#18794e"),("COGS",cog,"#6f4b3e"),("Expenses",other_exp,"#8f244e"),("Net Profit",net_profit,"#18794e" if net_profit>=0 else "#a83255")]
        mx=max([abs(v) for _,v,_ in vals]+[1])
        x=40
        for label,v,color in vals:
            h=int(95*abs(v)/mx)
            chart.create_rectangle(x,125-h,x+110,125,fill=color,outline=color)
            chart.create_text(x+55,135,text=label,font=("Segoe UI",9,"bold"),fill="#1e1b24")
            chart.create_text(x+55,125-h-12,text=M(v),font=("Segoe UI",8,"bold"),fill="#1e1b24")
            x+=150
    def edit_purchase(self, row):
        try:
            backup("before_edit")
        except Exception as backup_error:
            if not messagebox.askyesno("Backup unavailable", "A safety backup could not be created. Continue editing anyway?"):
                return
        win=tk.Toplevel(self); win.title("Edit Purchase"); win.geometry("430x470"); win.configure(bg="white")
        tk.Label(win,text="Edit Purchase",bg="white",font=("Segoe UI",17,"bold")).pack(pady=15)
        fields=[("Invoice No.","invoice"),("Vendor Name","vendor"),("Vendor PAN No.","pan"),("Product","product"),("Quantity","qty"),("Unit","unit"),("Unit Cost","price")]
        e={}; box=tk.Frame(win,bg="white"); box.pack(fill="x",padx=20)
        date_fields(box,0,e,row["date"] or "",row["bs_date"] or ad_to_bs(row["date"] or ""))
        extra=self.form(box,[("Invoice No.","invoice"),("Vendor Name","vendor"),("Vendor PAN No.","pan"),("Product","product"),("Quantity","qty"),("Unit","unit"),("Unit Cost","price")],start_row=2)
        e.update(extra)
        self._attach_quantity(box,e,6,str(row["qty"] or "1"))
        self._attach_unit(box,e,7,row["unit"] or "pcs")
        for key in ("invoice","vendor","pan","product","qty","price"):
            e[key].delete(0,"end"); e[key].insert(0,str(row[key] or ""))
        def save():
            try:
                normalize_dates(e, changed=e.get("_last_date_field"), show_error=True); q=float(e["qty"].get()); p=float(e["price"].get()); product=e["product"].get().strip()
                if q<=0 or p<0 or not product: raise ValueError
                db.execute("UPDATE purchases SET date=?,bs_date=?,invoice=?,vendor=?,pan=?,product=?,qty=?,unit=?,price=? WHERE id=?",
                           (e["date"].get(),e["bs_date"].get(),e["invoice"].get(),e["vendor"].get(),e["pan"].get(),product,q,e["unit"].get().strip() or "pcs",p,row["id"]))
                db.commit(); self._sync_legacy_accounting(); self._safe_backup(); win.destroy(); self.purchases()
            except ValueError:
                messagebox.showerror("Invalid entry","Check both dates, quantity, unit cost and product.")
        tk.Button(win,text="Save Changes",command=save,bg="#c33d70",fg="white",bd=0,padx=20,pady=8).pack(pady=15)

    def edit_selected_purchase(self, event=None):
        tree=getattr(self,"purchase_tree",None)
        if tree is None:
            messagebox.showerror("Edit Purchase", "The purchase table is not available.")
            return
        sel=tree.selection()
        if not sel:
            messagebox.showwarning("Select purchase", "Select a purchase row first.")
            return
        item=sel[0]
        # Treeview iid is the database id in the current table; tags are a fallback.
        rid=tree.item(item,"tags")[0] if tree.item(item,"tags") else item
        try:
            row=db.execute("SELECT * FROM purchases WHERE id=?", (int(rid),)).fetchone()
        except Exception:
            row=None
        if row is None:
            messagebox.showerror("Edit Purchase", "Could not find the selected record.")
            return
        self.edit_purchase(row)

    def edit_sale(self, row):
        try:
            backup("before_edit")
        except Exception as backup_error:
            if not messagebox.askyesno("Backup unavailable", "A safety backup could not be created. Continue editing anyway?"):
                return
        win=tk.Toplevel(self); win.title("Edit Sale"); win.geometry("470x520"); win.configure(bg="white")
        tk.Label(win,text="Edit Sale",bg="white",font=("Segoe UI",17,"bold")).pack(pady=15)
        e={}; box=tk.Frame(win,bg="white"); box.pack(fill="x",padx=20)
        date_fields(box,0,e,row["date"] or "",row["bs_date"] or ad_to_bs(row["date"] or ""))
        extra=self.form(box,[("Invoice No.","invoice"),("Customer","customer"),("Product","product"),("Quantity","qty"),("Selling Price","price"),("Payment Status","payment_status"),("Paid Amount","paid"),("Due Date","due_date")],start_row=2)
        e.update(extra)
        self._attach_quantity(box,e,5,str(row["qty"] or "1"))
        self._attach_unit(box,e,6,row["unit"] or "pcs")
        for key in ("invoice","customer","product","qty","price","payment_status","paid","due_date"):
            e[key].delete(0,"end"); e[key].insert(0,str(row[key] or ""))
        e["payment_status"]=ttk.Combobox(box,values=["Cash","Credit"],state="readonly")
        e["payment_status"].grid(row=8,column=1,sticky="ew",padx=20,pady=5)
        e["payment_status"].set(row["payment_status"] or "Cash")
        def save():
            try:
                normalize_dates(e, changed=e.get("_last_date_field"), show_error=True); q=float(e["qty"].get()); p=float(e["price"].get()); product=e["product"].get().strip()
                paid=float(e["paid"].get() or 0); status=e["payment_status"].get() or "Cash"
                if q<=0 or p<0 or paid<0 or paid>q*p or not product: raise ValueError
                if status=="Cash": paid=q*p
                available=stock_at_sale_date(product, e["unit"].get().strip() or "pcs", row["id"], e["date"].get(), row["created"] or "")
                if q>available:
                    messagebox.showerror("Stock error",f"Available stock on that date: {Q(available)}"); return
                db.execute("UPDATE sales SET date=?,bs_date=?,invoice=?,customer=?,product=?,qty=?,unit=?,price=?,payment_status=?,paid=?,due_date=? WHERE id=?",
                           (e["date"].get(),e["bs_date"].get(),e["invoice"].get(),e["customer"].get().strip(),product,q,e["unit"].get().strip() or "pcs",p,status,paid,e["due_date"].get().strip(),row["id"]))
                db.commit(); self._sync_legacy_accounting(); self._safe_backup(); win.destroy(); self.sales()
            except ValueError:
                messagebox.showerror("Invalid entry","Check both dates, quantity and price.")
        tk.Button(win,text="Save Changes",command=save,bg="#e3bf00",fg="#272000",bd=0,padx=20,pady=8).pack(pady=15)

    def edit_selected_sale(self, event=None):
        tree=getattr(self,"sales_tree",None)
        if tree is None:
            messagebox.showerror("Edit Sale", "The sale table is not available.")
            return
        sel=tree.selection()
        if not sel:
            messagebox.showwarning("Select sale", "Select a sale row first.")
            return
        item=sel[0]
        # Treeview iid is the database id in the current table; tags are a fallback.
        rid=tree.item(item,"tags")[0] if tree.item(item,"tags") else item
        try:
            row=db.execute("SELECT * FROM sales WHERE id=?", (int(rid),)).fetchone()
        except Exception:
            row=None
        if row is None:
            messagebox.showerror("Edit Sale", "Could not find the selected record.")
            return
        self.edit_sale(row)

    def _product_default_unit(self, product):
        try:
            row=db.execute("SELECT unit FROM products_master WHERE lower(name)=lower(?) LIMIT 1",(str(product or "").strip(),)).fetchone()
            return (row["unit"] or "pcs").strip() if row else "pcs"
        except Exception:
            return "pcs"

    def _attach_unit(self, parent, e, row, initial="pcs"):
        old=e.get("unit")
        if old is not None:
            try: old.destroy()
            except Exception: pass
        unit=ttk.Combobox(parent, values=["pcs","kg","g","L","ml","box","pack","dozen","set","unit"], width=18)
        unit.grid(row=row,column=1,sticky="ew",padx=20,pady=5)
        unit.set(initial or "pcs")
        e["unit"]=unit
        return unit

    def form(self,parent,fields,start_row=0):
        e={}
        for i,(label,key) in enumerate(fields,start_row):
            tk.Label(parent,text=label,bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).grid(row=i,column=0,sticky="w",padx=(24,12),pady=7)
            e[key]=tk.Entry(parent,relief="flat",bg="#f8f6fa",font=("Segoe UI",10),insertbackground="#24202a",
                             highlightbackground="#d8d0dc",highlightthickness=1)
            e[key].grid(row=i,column=1,sticky="ew",padx=(0,24),pady=7,ipady=5)
        parent.columnconfigure(1,weight=1); return e
    def purchases(self):
        self.clear(); self.heading("Purchases","Record and manage purchase transactions")
        # Form card
        f=self._make_card(self.body); f.pack(fill="x",pady=(0,10))
        e={}
        date_fields(f,0,e,datetime.now().strftime("%Y-%m-%d"))
        extra=self.form(f,[("Invoice No.","invoice"),("Vendor Name","vendor"),("Vendor PAN No.","pan"),("Product","product"),("Quantity","qty"),("Unit","unit"),("Unit Cost","price")],start_row=2)
        e.update(extra)
        self._attach_quantity(f,e,6)
        self._attach_unit(f,e,7)
        e["product"].bind("<FocusOut>",lambda _ : e["unit"].set(self._product_default_unit(e["product"].get())))
        bf=tk.Frame(f,bg="white"); bf.grid(row=9,column=0,columnspan=2,pady=(12,16))
        self._action_button(bf,"+  Add Purchase",lambda:self.add_purchase(e),"#c83d73").pack(side="left",padx=4)
        # Actions row
        actions=tk.Frame(self.body,bg="#f4f2f7"); actions.pack(fill="x",pady=(0,6))
        tk.Label(actions,text="Select a row, then:",bg="#f4f2f7",fg="#756d78",font=("Segoe UI",9)).pack(side="left",padx=(8,5))
        self._action_button(actions,"Edit Selected",self.edit_selected_purchase,"#3f6f8e").pack(side="left",padx=4)
        self._action_button(actions,"Delete Selected",self.delete_selected_purchase,"#a83255").pack(side="left",padx=4)
        self._action_button(actions,"Export Excel",self.export_purchases_xlsx,"#18794e").pack(side="left",padx=4)
        # Table card
        frame=self._make_card(self.body); frame.pack(fill="both",expand=True,pady=(0,4)); frame.configure(highlightthickness=1)
        self.purchase_tree=ttk.Treeview(frame,columns=("AD Date","BS Date","Invoice","Vendor","PAN","Product","Qty","Unit","Unit Cost","Total"),show="headings")
        purchase_widths={"AD Date":110,"BS Date":110,"Invoice":145,"Vendor":150,"PAN":120,"Product":180,"Qty":85,"Unit":85,"Unit Cost":120,"Total":125}
        for c in ("AD Date","BS Date","Invoice","Vendor","PAN","Product","Qty","Unit","Unit Cost","Total"):
            self.purchase_tree.heading(c,text=c); self.purchase_tree.column(c,width=purchase_widths[c],minwidth=70,stretch=False)
        self.purchase_tree.pack(side="top",fill="both",expand=True)
        scy=ttk.Scrollbar(frame,orient="vertical",command=self.purchase_tree.yview); scy.pack(side="right",fill="y")
        scx=ttk.Scrollbar(frame,orient="horizontal",command=self.purchase_tree.xview); scx.pack(side="bottom",fill="x")
        self.purchase_tree.configure(yscrollcommand=scy.set,xscrollcommand=scx.set)
        self.purchase_search_var=tk.StringVar()
        ps=tk.Frame(self.body,bg="#f4f2f7"); ps.pack(fill="x",before=frame,pady=(0,6))
        tk.Label(ps,text="Search purchases:",bg="#f4f2f7",fg="#756d78",font=("Segoe UI",9)).pack(side="left",padx=(8,5))
        pse=tk.Entry(ps,textvariable=self.purchase_search_var,width=32,relief="flat",bg="white",font=("Segoe UI",10),highlightbackground="#d8d0dc",highlightthickness=1); pse.pack(side="left",ipady=5)
        def filter_purchases(*_):
            q=self.purchase_search_var.get().strip().lower(); self.purchase_tree.delete(*self.purchase_tree.get_children())
            for p in db.execute("select * from purchases order by id desc"):
                hay=" ".join(str(p[k] or "") for k in ("date","bs_date","invoice","vendor","pan","product","unit")).lower()
                if q and q not in hay: continue
                self.purchase_tree.insert("", "end", iid=str(p["id"]), values=(p["date"],p["bs_date"] or ad_to_bs(p["date"]) or "—",p["invoice"] or "—",p["vendor"] or "—",p["pan"] or "—",p["product"],Q(p["qty"]),p["unit"] or "pcs",M(p["price"]),M(p["qty"]*p["price"])),tags=(str(p["id"]),))
        self.purchase_search_var.trace_add("write",filter_purchases)
        filter_purchases()
        self.purchase_tree.bind("<Double-1>",self.edit_selected_purchase)

    def add_purchase(self,e):
        try:
            q=float(e["qty"].get()); p=float(e["price"].get()); product=e["product"].get().strip()
            if q<=0 or p<0 or not product: raise ValueError
            normalize_dates(e, changed=e.get("_last_date_field"), show_error=True)
            invoice=e["invoice"].get().strip()
            if invoice and db.execute("select 1 from purchases where invoice=?",(invoice,)).fetchone():
                if not messagebox.askyesno("Duplicate invoice",f"Purchase invoice {invoice} already exists. Add another anyway?"): return
            db.execute("insert into purchases(date,bs_date,invoice,vendor,pan,product,qty,unit,price,created) values(?,?,?,?,?,?,?,?,?,?)",(e["date"].get(),e["bs_date"].get(),e["invoice"].get(),e["vendor"].get(),e["pan"].get(),product,q,e["unit"].get().strip() or "pcs",p,datetime.now().isoformat())); db.commit(); self._sync_legacy_accounting(); self._safe_backup(); self.purchases()
        except Exception: messagebox.showerror("Invalid entry","Check quantity, price and product.")
    def sales(self):
        self.clear(); self.heading("Sales","Record sales, manage cash and credit transactions")
        # Form card
        f=self._make_card(self.body); f.pack(fill="x",pady=(0,10))
        e={}; date_fields(f,0,e,datetime.now().strftime("%Y-%m-%d"))
        extra=self.form(f,[("Invoice No.","invoice"),("Customer","customer"),("Product","product"),("Quantity","qty"),("Unit","unit"),("Selling Price","price"),("Payment Status","payment_status"),("Paid Amount","paid"),("Due Date","due_date")],start_row=2)
        e.update(extra)
        self._attach_quantity(f,e,5)
        self._attach_unit(f,e,6)
        product_names=[r[0] for r in calc()[0].values()]
        e["product"].destroy(); e["product"]=ttk.Combobox(f,values=product_names,font=("Segoe UI",10))
        e["product"].grid(row=4,column=1,sticky="ew",padx=(0,24),pady=7,ipady=5)
        e["product"].bind("<<ComboboxSelected>>",lambda _ : e["unit"].set(self._product_default_unit(e["product"].get())))
        e["product"].bind("<FocusOut>",lambda _ : e["unit"].set(self._product_default_unit(e["product"].get())))
        e["payment_status"].destroy(); e["payment_status"]=ttk.Combobox(f,values=["Cash","Credit"],state="readonly",font=("Segoe UI",10))
        e["payment_status"].grid(row=8,column=1,sticky="ew",padx=(0,24),pady=7,ipady=5); e["payment_status"].set("Cash")
        e["paid"].insert(0,"0")
        bf=tk.Frame(f,bg="white"); bf.grid(row=11,column=0,columnspan=2,pady=(12,16))
        self._action_button(bf,"+  Add Sale",lambda:self.add_sale(e),"#b38f00").pack(side="left",padx=4)
        # Actions row
        actions=tk.Frame(self.body,bg="#f4f2f7"); actions.pack(fill="x",pady=(0,6))
        tk.Label(actions,text="Select a row, then:",bg="#f4f2f7",fg="#756d78",font=("Segoe UI",9)).pack(side="left",padx=(8,5))
        self._action_button(actions,"Edit Selected",self.edit_selected_sale,"#3f6f8e").pack(side="left",padx=4)
        self._action_button(actions,"Delete Selected",self.delete_selected_sale,"#a83255").pack(side="left",padx=4)
        self._action_button(actions,"Export Invoice PDF",self.export_invoice_pdf,"#2c252b").pack(side="left",padx=4)
        self._action_button(actions,"Export Excel",self.export_sales_xlsx,"#18794e").pack(side="left",padx=4)
        # Search + Table
        ss=tk.Frame(self.body,bg="#f4f2f7"); ss.pack(fill="x",pady=(0,6))
        tk.Label(ss,text="Search sales:",bg="#f4f2f7",fg="#756d78",font=("Segoe UI",9)).pack(side="left",padx=(8,5))
        self.sales_search_var=tk.StringVar()
        sse=tk.Entry(ss,textvariable=self.sales_search_var,width=32,relief="flat",bg="white",font=("Segoe UI",10),highlightbackground="#d8d0dc",highlightthickness=1)
        sse.pack(side="left",ipady=5)
        frame=self._make_card(self.body); frame.pack(fill="both",expand=True,pady=(0,4)); frame.configure(highlightthickness=1)
        self.sales_tree=ttk.Treeview(frame,columns=("AD Date","BS Date","Invoice","Customer","Product","Qty","Unit","Selling Price","Total","Profit","Payment"),show="headings")
        for c in ("AD Date","BS Date","Invoice","Customer","Product","Qty","Unit","Selling Price","Total","Profit","Payment"):
            self.sales_tree.heading(c,text=c); self.sales_tree.column(c,width=125)
        self.sales_tree.pack(side="top",fill="both",expand=True)
        scy=ttk.Scrollbar(frame,orient="vertical",command=self.sales_tree.yview); scy.pack(side="right",fill="y")
        scx=ttk.Scrollbar(frame,orient="horizontal",command=self.sales_tree.xview); scx.pack(side="bottom",fill="x")
        self.sales_tree.configure(yscrollcommand=scy.set,xscrollcommand=scx.set)
        def filter_sales(*_):
            q=self.sales_search_var.get().strip().lower(); self.sales_tree.delete(*self.sales_tree.get_children())
            d2,*rest2=calc(); sale_cogs2=rest2[-1]
            for s in db.execute("select * from sales order by id desc"):
                hay=" ".join(str(s[k] or "") for k in ("date","bs_date","invoice","customer","product","unit","payment_status","due_date")).lower()
                if q and q not in hay: continue
                c=sale_cogs2.get(s["id"],0.0)
                self.sales_tree.insert("", "end", iid=str(s["id"]), values=(s["date"],s["bs_date"] or ad_to_bs(s["date"]) or "—",s["invoice"] or "—",s["customer"] or "—",s["product"],Q(s["qty"]),s["unit"] or "pcs",M(s["price"]),M(s["qty"]*s["price"]),M(s["qty"]*float(s["price"])-c),s["payment_status"] or "Cash"),tags=(str(s["id"]),))
        self.sales_search_var.trace_add("write",filter_sales)
        d,*rest=calc(); sale_cogs=rest[-1]
        filter_sales()
        self.sales_tree.bind("<Double-1>",self.edit_selected_sale)

    def add_sale(self,e):
        try:
            q=float(e["qty"].get()); p=float(e["price"].get()); product=e["product"].get().strip()
            status=e["payment_status"].get() or "Cash"; paid=float(e["paid"].get() or 0)
            if status=="Cash": paid=q*p
            if q<=0 or p<0 or paid<0 or paid>q*p or not product: raise ValueError
            normalize_dates(e, changed=e.get("_last_date_field"), show_error=True)
            invoice=e["invoice"].get().strip()
            if invoice and db.execute("select 1 from sales where invoice=?",(invoice,)).fetchone():
                if not messagebox.askyesno("Duplicate invoice",f"Sale invoice {invoice} already exists. Add another anyway?"): return
            created=datetime.now().isoformat()
            available=stock_at_sale_date(product, e["unit"].get().strip() or "pcs", -1, e["date"].get(), created)
            if q>available: messagebox.showerror("Stock error",f"Available stock on that date: {Q(available)}"); return
            if status=="Credit" and not e["due_date"].get().strip(): raise ValueError
            db.execute("""insert into sales(date,bs_date,invoice,product,qty,unit,price,created,customer,payment_status,paid,due_date)
                          values(?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (e["date"].get(),e["bs_date"].get(),e["invoice"].get(),product,q,e["unit"].get().strip() or "pcs",p,created,e["customer"].get().strip(),status,paid,e["due_date"].get().strip()))
            db.commit(); self._sync_legacy_accounting(); self._safe_backup(); self.sales()
        except ValueError: messagebox.showerror("Invalid entry","Check dates, quantity, price, payment and due date.")
    def expenditures(self):
        self.clear(); self.heading("Expenditures","Track business expenses and overhead costs")
        f=self._make_card(self.body); f.pack(fill="x",pady=(0,10))
        e={}
        date_fields(f,0,e,datetime.now().strftime("%Y-%m-%d"))
        extra=self.form(f,[("Category","category"),("Description","description"),("Amount","amount")],start_row=2)
        e.update(extra)
        bf=tk.Frame(f,bg="white"); bf.grid(row=6,column=0,columnspan=2,pady=(12,16))
        self._action_button(bf,"+  Add Expenditure",lambda:self.add_expenditure(e),"#6b5b73").pack(side="left",padx=4)
        actions=tk.Frame(self.body,bg="#f4f2f7"); actions.pack(fill="x",pady=(0,6))
        self._action_button(actions,"Edit Selected",self.edit_selected_expenditure,"#3f6f8e").pack(side="left",padx=4)
        self._action_button(actions,"Delete Selected",self.delete_selected_expenditure,"#a83255").pack(side="left",padx=4)
        frame=self._make_card(self.body); frame.pack(fill="both",expand=True,pady=(0,4)); frame.configure(highlightthickness=1)
        self.exp_tree=ttk.Treeview(frame,columns=("AD Date","BS Date","Category","Description","Amount"),show="headings")
        for c in ("AD Date","BS Date","Category","Description","Amount"):
            self.exp_tree.heading(c,text=c); self.exp_tree.column(c,width=180)
        self.exp_tree.pack(side="left",fill="both",expand=True)
        sc=ttk.Scrollbar(frame,orient="vertical",command=self.exp_tree.yview); sc.pack(side="right",fill="y")
        scx=ttk.Scrollbar(frame,orient="horizontal",command=self.exp_tree.xview); scx.pack(side="bottom",fill="x")
        self.exp_tree.configure(yscrollcommand=sc.set,xscrollcommand=scx.set)
        for x in db.execute("select * from expenditures order by id desc"):
            self.exp_tree.insert("", "end", values=(x["date"],x["bs_date"] or ad_to_bs(x["date"]) or "—",x["category"],x["description"],M(x["amount"])),tags=(str(x["id"]),))
        self.exp_tree.bind("<Double-1>",self.edit_selected_expenditure)

    def add_expenditure(self,e):
        try:
            amount=float(e["amount"].get()); category=e["category"].get().strip()
            if amount<0 or not category: raise ValueError
            normalize_dates(e, changed=e.get("_last_date_field"), show_error=True)
            db.execute("insert into expenditures(date,bs_date,category,description,amount,created) values(?,?,?,?,?,?)",
                       (e["date"].get(),e["bs_date"].get(),category,e["description"].get().strip(),amount,datetime.now().isoformat()))
            db.commit(); self._sync_legacy_accounting(); self._safe_backup(); self.expenditures()
        except ValueError:
            messagebox.showerror("Invalid entry","Enter a category and a valid amount.")

    def edit_selected_expenditure(self,event=None):
        sel=self.exp_tree.selection() if hasattr(self,"exp_tree") else ()
        if not sel:
            messagebox.showwarning("Select expenditure","Select an expenditure row first."); return
        rid=self.exp_tree.item(sel[0],"tags")[0]
        row=db.execute("select * from expenditures where id=?",(rid,)).fetchone()
        if not row: return
        win=tk.Toplevel(self); win.title("Edit Expenditure"); win.geometry("420x340"); win.configure(bg="white")
        tk.Label(win,text="Edit Expenditure",bg="white",font=("Segoe UI",17,"bold")).pack(pady=15)
        e={}; box=tk.Frame(win,bg="white"); box.pack(fill="x",padx=20)
        date_fields(box,0,e,row["date"] or "",row["bs_date"] or ad_to_bs(row["date"] or ""))
        extra=self.form(box,[("Category","category"),("Description","description"),("Amount","amount")],start_row=2)
        e.update(extra)
        for key in ("category","description","amount"):
            e[key].delete(0,"end"); e[key].insert(0,str(row[key] or ""))
        def save():
            try:
                normalize_dates(e, changed=e.get("_last_date_field"), show_error=True); amount=float(e["amount"].get()); category=e["category"].get().strip()
                if amount<0 or not category: raise ValueError
                db.execute("update expenditures set date=?,bs_date=?,category=?,description=?,amount=? where id=?",
                           (e["date"].get(),e["bs_date"].get(),category,e["description"].get().strip(),amount,row["id"]))
                db.commit(); self._sync_legacy_accounting(); self._safe_backup(); win.destroy(); self.expenditures()
            except ValueError:
                messagebox.showerror("Invalid entry","Check both dates and the amount.")
        tk.Button(win,text="Save Changes",command=save,bg="#5b5260",fg="white",bd=0,padx=20,pady=8).pack(pady=15)

    def inventory(self):
        self.clear(); self.heading("Inventory","Live stock levels by product and unit")
        d,*_=calc()
        # Summary cards
        summary=tk.Frame(self.body,bg="#f4f2f7"); summary.pack(fill="x",pady=(0,10))
        total_stock=sum(max(0,r[6]) for r in d.values())
        total_value=sum(max(0,r[6])*r[5] for r in d.values())
        low_count=sum(1 for r in d.values() if 0<r[6]<=5)
        out_count=sum(1 for r in d.values() if r[6]<=0)
        self._metric_card(summary,"Total Products",str(len(d)),"#1e1b24")
        self._metric_card(summary,"Total Stock Units",f"{total_stock:,.0f}","#3f6f8e")
        self._metric_card(summary,"Stock Value",M(total_value),"#18794e")
        self._metric_card(summary,"Low Stock Items",str(low_count),"#b38f00" if low_count>0 else "#18794e")
        frame=self._make_card(self.body); frame.pack(fill="both",expand=True,pady=(0,8))
        tr=ttk.Treeview(frame,columns=("Product","Unit","Purchased","Sold","Stock","Avg Cost","Stock Value","Status"),show="headings")
        tr.tag_configure("low",background="#fff8f0")
        tr.tag_configure("out",background="#fef0f0")
        for c in ("Product","Unit","Purchased","Sold","Stock","Avg Cost","Stock Value","Status"):
            tr.heading(c,text=c); tr.column(c,width=130)
        tr.pack(side="top",fill="both",expand=True)
        sy=ttk.Scrollbar(frame,orient="vertical",command=tr.yview); sy.pack(side="right",fill="y")
        sx=ttk.Scrollbar(frame,orient="horizontal",command=tr.xview); sx.pack(side="bottom",fill="x")
        tr.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        for r in d.values():
            status="OUT OF STOCK" if r[6]<=0 else ("LOW STOCK" if r[6]<=5 else "OK")
            tag="out" if r[6]<=0 else ("low" if r[6]<=5 else "")
            tr.insert("", "end",values=(r[0],r[1],Q(r[2]),Q(r[3]),Q(r[6]),M(r[5]),M(max(0,r[6])*r[5]),status),tags=(tag,))
        def open_ledger(_=None):
            sel=tr.selection()
            if sel:
                vals=tr.item(sel[0],"values")
                self.show_stock_ledger(vals[0], vals[1])
        tr.bind("<Double-1>",open_ledger)
        bf=tk.Frame(self.body,bg="#f4f2f7"); bf.pack(fill="x",pady=(6,0))
        self._action_button(bf,"View Stock Ledger",open_ledger,"#2c252b").pack(side="left",padx=4)

    def show_stock_ledger(self, product, unit="pcs"):
        self.clear()
        self.heading(f"Stock Ledger — {product} [{unit}]", "Chronological movement and weighted-average cost")
        rows=[]; stock=0.0; value=0.0; tx=[]
        for p in db.execute("select * from purchases where lower(product)=lower(?) AND lower(COALESCE(unit,'pcs'))=lower(?)",(product,unit)):
            tx.append((_date_key(p["date"],p["created"]),0,p["id"],p))
        for s in db.execute("select * from sales where lower(product)=lower(?) AND lower(COALESCE(unit,'pcs'))=lower(?)",(product,unit)):
            tx.append((_date_key(s["date"],s["created"]),1,s["id"],s))
        tx.sort(key=lambda x:(x[0],x[1],x[2]))
        sale_cogs=calc()[-1]
        frame=tk.Frame(self.body,bg="white"); frame.pack(fill="both",expand=True,pady=10)
        tree=ttk.Treeview(frame,columns=("AD Date","B.S. Date","Type","Invoice","Qty","Unit","Unit Cost","Stock","Avg Cost","Value"),show="headings")
        for c in ("AD Date","B.S. Date","Type","Invoice","Qty","Unit","Unit Cost","Stock","Avg Cost","Value"):
            tree.heading(c,text=c); tree.column(c,width=120)
        tree.pack(side="top",fill="both",expand=True)
        sy=ttk.Scrollbar(frame,orient="vertical",command=tree.yview); sy.pack(side="right",fill="y")
        sx=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview); sx.pack(side="bottom",fill="x")
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        for _,typ,rid,row in tx:
            if typ==0:
                q=float(row["qty"]); cost=float(row["price"]); value += q*cost; stock += q
                avg=value/stock if stock else 0
                tree.insert("", "end",values=(row["date"],row["bs_date"] or ad_to_bs(row["date"]),"PURCHASE",row["invoice"] or "—",Q(q),row["unit"] or "pcs",M(cost),Q(stock),M(avg),M(value)))
            else:
                q=float(row["qty"]); c=sale_cogs.get(rid,0.0); unit_cost=c/q if q else 0; stock -= q; value -= c
                if stock < 0: stock=0
                avg=value/stock if stock else 0
                tree.insert("", "end",values=(row["date"],row["bs_date"] or ad_to_bs(row["date"]),"SALE",row["invoice"] or "—",Q(-q),row["unit"] or "pcs",M(unit_cost),Q(stock),M(avg),M(value)))
        tk.Button(self.body,text="← Back to Inventory",command=self.inventory,bg="#2c252b",fg="white",bd=0,padx=16,pady=7).pack(anchor="w",pady=5)

    def search_all(self):
        """Search all relevant records using the actual database schema."""
        q = self.search_var.get().strip()
        if q == "Product, Invoice, SKU, Vendor, Customer...": q = ""
        if not q:
            messagebox.showinfo(
                "Search",
                "Enter a product, invoice, vendor, PAN, customer, SKU, barcode or other search term."
            )
            return

        like = f"%{q}%"
        rows = []

        def add_rows(sql, params, formatter):
            try:
                for r in db.execute(sql, params):
                    rows.append(formatter(r))
            except Exception as e:
                # A search must never crash the application if an optional table/field
                # is unavailable in an older database.
                print("Search skipped:", e)

        # Purchases: actual schema includes vendor/pan/unit.
        add_rows(
            """SELECT date, 'Purchase' AS type, product, invoice, vendor AS party,
                      qty, unit, price
               FROM purchases
               WHERE product LIKE ? OR invoice LIKE ? OR vendor LIKE ?
                  OR pan LIKE ? OR unit LIKE ?
               ORDER BY date DESC, id DESC""",
            (like, like, like, like, like),
            lambda r: (r["date"], r["type"], r["product"], r["invoice"] or "—",
                       r["party"] or "—", Q(r["qty"]), r["unit"] or "pcs", M(r["price"]))
        )

        # Sales: the current schema has no customer column, so never query one.
        add_rows(
            """SELECT date, 'Sale' AS type, product, invoice, '' AS party,
                      qty, unit, price
               FROM sales
               WHERE product LIKE ? OR invoice LIKE ? OR unit LIKE ?
               ORDER BY date DESC, id DESC""",
            (like, like, like),
            lambda r: (r["date"], r["type"], r["product"], r["invoice"] or "—",
                       "—", Q(r["qty"]), r["unit"] or "pcs", M(r["price"]))
        )

        add_rows(
            """SELECT date, 'Expenditure' AS type, category AS product,
                      description AS invoice, category AS party,
                      NULL AS qty, '' AS unit, amount AS price
               FROM expenditures
               WHERE category LIKE ? OR description LIKE ?
               ORDER BY date DESC, id DESC""",
            (like, like),
            lambda r: (r["date"], r["type"], r["product"], r["invoice"] or "—",
                       r["party"] or "—", "—", "—", M(r["price"]))
        )

        # Product master.
        add_rows(
            """SELECT '' AS date, 'Product' AS type, name AS product,
                      sku AS invoice, category AS party, NULL AS qty,
                      unit, selling_price AS price
               FROM products_master
               WHERE name LIKE ? OR sku LIKE ? OR barcode LIKE ?
                  OR category LIKE ? OR brand LIKE ? OR unit LIKE ?
               ORDER BY name""",
            (like, like, like, like, like, like),
            lambda r: ("", r["type"], r["product"], r["invoice"] or "—",
                       r["party"] or "—", "—", r["unit"] or "pcs", M(r["price"]))
        )

        # Customers.
        add_rows(
            """SELECT '' AS date, 'Customer' AS type, name AS product,
                      '' AS invoice, phone AS party, NULL AS qty,
                      '' AS unit, NULL AS price
               FROM customers
               WHERE name LIKE ? OR phone LIKE ? OR address LIKE ?
                  OR pan LIKE ? OR notes LIKE ?
               ORDER BY name""",
            (like, like, like, like, like),
            lambda r: ("", r["type"], r["product"], "—",
                       r["party"] or "—", "—", "—", "—")
        )

        # Suppliers.
        add_rows(
            """SELECT '' AS date, 'Supplier' AS type, name AS product,
                      '' AS invoice, phone AS party, NULL AS qty,
                      '' AS unit, NULL AS price
               FROM suppliers
               WHERE name LIKE ? OR phone LIKE ? OR address LIKE ?
                  OR pan LIKE ? OR payment_terms LIKE ? OR notes LIKE ?
               ORDER BY name""",
            (like, like, like, like, like, like),
            lambda r: ("", r["type"], r["product"], "—",
                       r["party"] or "—", "—", "—", "—")
        )

        win = tk.Toplevel(self)
        win.title(f"Search: {q}")
        win.geometry("1050x600")
        win.minsize(750, 420)

        header = tk.Frame(win, bg="white")
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(
            header, text=f"Search results for: {q}",
            bg="white", font=("Segoe UI", 12, "bold")
        ).pack(side="left")

        sf = tk.Frame(win, bg="white")
        sf.pack(fill="both", expand=True, padx=12, pady=12)

        cols = ("Date", "Type", "Item", "Invoice / SKU", "Party",
                "Quantity", "Unit", "Amount")
        tr = ttk.Treeview(sf, columns=cols, show="headings")
        widths = {
            "Date": 100, "Type": 115, "Item": 230,
            "Invoice / SKU": 150, "Party": 180,
            "Quantity": 100, "Unit": 80, "Amount": 120
        }
        for c in cols:
            tr.heading(c, text=c)
            tr.column(c, width=widths[c], minwidth=70, stretch=False)

        sy = ttk.Scrollbar(sf, orient="vertical", command=tr.yview)
        sx = ttk.Scrollbar(sf, orient="horizontal", command=tr.xview)
        tr.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

        tr.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        sf.grid_rowconfigure(0, weight=1)
        sf.grid_columnconfigure(0, weight=1)

        for row in rows:
            tr.insert("", "end", values=row)

        tk.Label(
            win,
            text=f"{len(rows)} result(s)",
            anchor="w",
            bg="white"
        ).pack(fill="x", padx=12, pady=(0, 10))

        # Mouse-wheel scrolling on the results table.
        def wheel(event):
            tr.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        tr.bind("<MouseWheel>", wheel)
        tr.bind("<Button-4>", lambda e: (tr.yview_scroll(-1, "units"), "break")[1])
        tr.bind("<Button-5>", lambda e: (tr.yview_scroll(1, "units"), "break")[1])


    def export_xlsx(self):
        """Export business data to a standards-compliant XLSX without openpyxl."""
        from tkinter import filedialog, messagebox
        from pathlib import Path as _Path

        config_file = _Path(EXP) / "inventory_export_location.txt"
        try:
            saved_dir = config_file.read_text(encoding="utf-8").strip()
        except Exception:
            saved_dir = ""
        if not saved_dir or not _Path(saved_dir).is_dir():
            saved_dir = EXP

        path=filedialog.asksaveasfilename(
            initialdir=saved_dir,
            title="Save Excel Export",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook","*.xlsx")]
        )
        if not path:
            return

        try:
            d,sp,rev,cog,prof,other_exp,net_profit,sale_cogs=calc()

            purchases=[]
            for r in db.execute("select * from purchases order by date,created,id"):
                purchases.append([
                    r["date"], r["bs_date"], r["invoice"], r["vendor"], r["pan"],
                    r["product"], r["qty"], r["unit"] or "pcs", r["price"], float(r["qty"] or 0)*float(r["price"] or 0)
                ])

            sales=[]
            for r in db.execute("select * from sales order by date,created,id"):
                qty=float(r["qty"] or 0); price=float(r["price"] or 0)
                c=float(sale_cogs.get(r["id"],0))
                sales.append([
                    r["date"], r["bs_date"], r["invoice"], r["customer"], r["product"],
                    qty, r["unit"] or "pcs", price, qty*price, c, qty*price-c,
                    r["payment_status"], r["paid"], r["due_date"]
                ])

            expenditures=[
                [r["date"],r["bs_date"],r["category"],r["description"],r["amount"]]
                for r in db.execute("select * from expenditures order by date,created,id")
            ]

            stock=[]
            for k,v in sorted(d.items()):
                # d values: name, total purchased, sold, remaining cost value, avg cost, current qty
                stock.append([v[0],v[1],v[2],v[3],v[6],v[5],v[4]])

            sheets=[
                ("Summary",["Metric","Amount"],[
                    ["Purchase Value",sp],
                    ["Sales Revenue",rev],
                    ["Cost of Goods Sold",cog],
                    ["Gross Profit",prof],
                    ["Other Expenditures",other_exp],
                    ["Net Profit",net_profit],
                ]),
                ("Purchases",
                 ["AD Date","B.S. Date","Invoice No.","Vendor Name","Vendor PAN",
                  "Product","Quantity","Unit","Unit Cost","Total Purchase"],
                 purchases),
                ("Sales",
                 ["AD Date","B.S. Date","Invoice No.","Customer","Product","Quantity","Unit",
                  "Selling Price","Sales Revenue","Cost of Goods Sold","Profit",
                  "Payment Status","Paid Amount","Due Date"],
                 sales),
                ("Expenditures",
                 ["AD Date","B.S. Date","Category","Description","Amount"],
                 expenditures),
                ("Stock Summary",
                 ["Product","Unit","Purchased Quantity","Sold Quantity","Current Stock",
                  "Average Cost","Stock Value"],
                 stock)
            ]

            _xlsx_write(path,sheets)

            try:
                config_file.write_text(str(_Path(path).parent),encoding="utf-8")
            except Exception:
                pass

            messagebox.showinfo(
                "Export Complete",
                f"Excel file exported successfully.\n\n{path}"
            )
        except Exception as exc:
            messagebox.showerror(
                "Excel Export Failed",
                "Could not export the Excel file.\n\n"+str(exc)
            )

    def _ask_xlsx_path(self, title, default_name):
        from tkinter import filedialog
        config_file=Path(EXP)/"inventory_export_location.txt"
        try: saved_dir=config_file.read_text(encoding="utf-8").strip()
        except Exception: saved_dir=""
        if not saved_dir or not Path(saved_dir).is_dir(): saved_dir=EXP
        path=filedialog.asksaveasfilename(initialdir=saved_dir,initialfile=default_name,
            title=title,defaultextension=".xlsx",filetypes=[("Excel Workbook","*.xlsx")])
        if path:
            try: config_file.write_text(str(Path(path).parent),encoding="utf-8")
            except Exception: pass
        return path or None

    def export_purchases_xlsx(self):
        """Export detailed purchase records to Excel."""
        path=self._ask_xlsx_path("Export Purchases to Excel","purchases_detail.xlsx")
        if not path: return
        try:
            rows=[]; total=0.0
            for r in db.execute("select * from purchases order by date,created,id"):
                line=float(r["qty"] or 0)*float(r["price"] or 0); total+=line
                rows.append([r["date"],r["bs_date"],r["invoice"],r["vendor"],r["pan"],
                             r["product"],float(r["qty"] or 0),r["unit"] or "pcs",float(r["price"] or 0),line])
            rows.append([])
            rows.append(["","","","","","","","","TOTAL",total])
            _xlsx_write(path,[("Purchases",
                ["AD Date","B.S. Date","Invoice No.","Vendor Name","Vendor PAN",
                 "Product","Quantity","Unit","Unit Cost","Total Purchase"],rows)])
            messagebox.showinfo("Export Complete",f"Purchases exported successfully.\n\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Failed","Could not export purchases.\n\n"+str(exc))

    def export_sales_xlsx(self):
        """Export detailed sales records with cost and profit to Excel."""
        path=self._ask_xlsx_path("Export Sales to Excel","sales_detail.xlsx")
        if not path: return
        try:
            sale_cogs=calc()[-1]
            rows=[]; tot_rev=tot_profit=0.0
            for r in db.execute("select * from sales order by date,created,id"):
                qty=float(r["qty"] or 0); price=float(r["price"] or 0)
                rev=qty*price; c=float(sale_cogs.get(r["id"],0)); prof=rev-c
                tot_rev+=rev; tot_profit+=prof
                rows.append([r["date"],r["bs_date"],r["invoice"],r["customer"],r["product"],
                             qty,r["unit"] or "pcs",price,rev,c,prof,
                             r["payment_status"],float(r["paid"] or 0),r["due_date"]])
            rows.append([])
            rows.append(["","","","","","","","TOTAL REVENUE",tot_rev,"",tot_profit,"","",""])
            _xlsx_write(path,[("Sales",
                ["AD Date","B.S. Date","Invoice No.","Customer","Product","Quantity","Unit",
                 "Selling Price","Sales Revenue","Cost of Goods Sold","Profit",
                 "Payment Status","Paid Amount","Due Date"],rows)])
            messagebox.showinfo("Export Complete",f"Sales exported successfully.\n\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Failed","Could not export sales.\n\n"+str(exc))

    def export_invoice_pdf(self):
        if not getattr(self,"sales_tree",None): return
        sel=self.sales_tree.selection()
        if not sel:
            messagebox.showwarning("Invoice","Select a sale first."); return
        rid=self.sales_tree.item(sel[0],"tags")[0]
        s=db.execute("select * from sales where id=?",(rid,)).fetchone()
        if not s:return
        path=filedialog.asksaveasfilename(initialdir=EXP,defaultextension=".pdf",filetypes=[("PDF","*.pdf")])
        if not path:return
        try:
            from reportlab.pdfgen import canvas
            c=canvas.Canvas(path)
            c.setFont("Helvetica-Bold",18); c.drawString(50,800,"SMART INVENTORY")
            c.setFont("Helvetica",11)
            lines=[f"Invoice: {s['invoice'] or '—'}",f"AD Date: {s['date']}",f"B.S. Date: {s['bs_date'] or ad_to_bs(s['date'])}",
                   f"Customer: {s['customer'] or 'Cash Customer'}",f"Product: {s['product']}",f"Quantity: {Q(s['qty'])}",
                   f"Selling Price: {M(s['price'])}",f"Total: {M(s['qty']*s['price'])}",f"Payment: {s['payment_status'] or 'Cash'}",
                   f"Paid: {M(s['paid'])}",f"Due: {M(max(0,s['qty']*s['price']-float(s['paid'] or 0)))}"]
            y=765
            for line in lines: c.drawString(55,y,line); y-=24
            c.save(); messagebox.showinfo("Invoice","PDF invoice created.")
        except ImportError:
            messagebox.showerror("PDF invoice","Install reportlab or rebuild the EXE with the updated requirements.")
        except Exception as ex:
            messagebox.showerror("Invoice failed",str(ex))

    def reports(self):
        self.clear(); self.heading("Reports & Data","Business reports, exports and local backups")
        d,sp,rev,cog,prof,other_exp,net_profit,sale_cogs=calc()
        # Summary metrics row
        metrics_row=tk.Frame(self.body,bg="#f4f2f7"); metrics_row.pack(fill="x",pady=(0,12))
        for title,val,col in [("Sales Revenue",rev,"#18794e"),("Trading Profit",prof,"#18794e" if prof>=0 else "#a83255"),("Expenses",other_exp,"#8f244e"),("Net Profit",net_profit,"#18794e" if net_profit>=0 else "#a83255")]:
            self._metric_card(metrics_row,title,M(val),col)
        # Action buttons grid (3 rows x 4 cols)
        actions_card=self._make_card(self.body); actions_card.pack(fill="x",pady=(0,12))
        tk.Label(actions_card,text="ACTIONS & TOOLS",bg="white",fg="#554c58",font=("Segoe UI",9,"bold")).pack(anchor="w",padx=18,pady=(14,10))
        btn_grid=tk.Frame(actions_card,bg="white"); btn_grid.pack(fill="x",padx=18,pady=(0,16))
        btn_items=[("Export CSV",self.csv,"#2c252b"),("Export Excel",self.export_xlsx,"#18794e"),("Import Excel",self.import_excel,"#8e3f78"),("Excel Template",self.download_excel_template,"#3f6f8e"),
                    ("Purchases Excel",self.export_purchases_xlsx,"#c83d73"),("Sales Excel",self.export_sales_xlsx,"#b38f00"),("Business Center",self.business_center,"#6b5b73"),("Accounting",self.accounting_center,"#7a4e9a"),
                    ("Business Dashboard",self.professional_dashboard,"#4f6d7a"),("Data Protection",self.data_protection_center,"#18794e"),("Create Backup",self._manual_backup,"#2c252b"),("Restore Backup",self.restore_backup,"#a83255")]
        for i,(text,cmd,color) in enumerate(btn_items):
            r,c=divmod(i,4)
            self._action_button(btn_grid,text,cmd,color).grid(row=r,column=c,padx=4,pady=4,sticky="ew")
        for c in range(4): btn_grid.columnconfigure(c,weight=1)
        # Date range filter
        rf=tk.Frame(self.body,bg="#f4f2f7"); rf.pack(fill="x",pady=(8,8))
        tk.Label(rf,text="Date range (AD):",bg="#f4f2f7",fg="#756d78",font=("Segoe UI",9)).pack(side="left",padx=4)
        from_var=tk.StringVar(value="")
        to_var=tk.StringVar(value="")
        from_e=tk.Entry(rf,textvariable=from_var,width=12,relief="flat",bg="white",font=("Segoe UI",10),highlightbackground="#d8d0dc",highlightthickness=1)
        from_e.pack(side="left",padx=4,ipady=4)
        tk.Label(rf,text="to",bg="#f4f2f7",fg="#756d78").pack(side="left")
        to_e=tk.Entry(rf,textvariable=to_var,width=12,relief="flat",bg="white",font=("Segoe UI",10),highlightbackground="#d8d0dc",highlightthickness=1)
        to_e.pack(side="left",padx=4,ipady=4)
        def apply_range():
            a,b=from_var.get().strip(),to_var.get().strip()
            try:
                if a: ad_date.fromisoformat(a)
                if b: ad_date.fromisoformat(b)
                rows=[]
                for s in db.execute("select * from sales order by date,created,id"):
                    if (not a or s["date"]>=a) and (not b or s["date"]<=b):
                        c=sale_cogs.get(s["id"],0); rows.append((s["date"],s["product"],Q(s["qty"]),s["unit"] or "pcs",M(s["qty"]*s["price"]),M(c),M(s["qty"]*s["price"]-c)))
                win=tk.Toplevel(self); win.title("Date-range Sales Report"); win.geometry("800x450")
                self.tree(win,["AD Date","Product","Qty","Unit","Revenue","Cost of Goods Sold","Profit"],rows)
            except ValueError: messagebox.showerror("Invalid range","Use YYYY-MM-DD for both dates.")
        self._action_button(rf,"Generate Report",apply_range,"#5b5260").pack(side="left",padx=8)
        # Report tables
        tk.Label(self.body,text="PROFIT BY PRODUCT",bg="#f4f2f7",fg="#1e1b24",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(14,6))
        product_rows=[]
        for key,r in d.items():
            sold_rev=0.0; pcogs=0.0
            for sr in db.execute("select * from sales where lower(product)=lower(?) AND lower(COALESCE(unit,'pcs'))=lower(?)",(r[0],r[1])):
                sold_rev += float(sr["qty"])*float(sr["price"]); pcogs += sale_cogs.get(sr["id"],0.0)
            product_rows.append((r[0],r[1],M(sold_rev),M(pcogs),M(sold_rev-pcogs),Q(r[6])))
        self.tree(self.body,["Product","Unit","Revenue","Cost of Goods Sold","Profit","Stock"],product_rows)
        tk.Label(self.body,text="VENDOR-WISE PURCHASES",bg="#f4f2f7",fg="#1e1b24",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(14,6))
        vendor_rows=[]
        for v in db.execute("select coalesce(vendor,'') vendor,sum(qty*price) total,count(*) count from purchases group by vendor order by total desc"):
            vendor_rows.append((v["vendor"] or "—",M(v["total"]),v["count"]))
        self.tree(self.body,["Vendor","Purchase Value","Transactions"],vendor_rows)
        tk.Label(self.body,text="CURRENT STOCK",bg="#f4f2f7",fg="#1e1b24",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(14,6))
        low=[(r[0],r[1],Q(r[6])) for r in d.values() if r[6] <= 5]
        if low:
            tk.Label(self.body,text="Low stock: " + ", ".join(f"{n} [{u}] ({q})" for n,u,q in low),bg="#fff3cd",fg="#7a5b00",anchor="w",padx=12,pady=8).pack(fill="x",pady=5)
        tk.Label(self.body,text="RECEIVABLES",bg="#f4f2f7",fg="#1e1b24",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(14,6))
        rec=[]
        for s in db.execute("select * from sales where payment_status='Credit' order by due_date"):
            due=max(0,float(s["qty"])*float(s["price"])-float(s["paid"] or 0))
            if due>0: rec.append((s["customer"] or "—",s["invoice"] or "—",s["due_date"] or "—",M(due)))
        if rec: self.tree(self.body,["Customer","Invoice","Due Date","Amount Due"],rec)
        else: tk.Label(self.body,text="No outstanding receivables.",bg="#f4f2f7",fg="#18794e",font=("Segoe UI",10)).pack(anchor="w")
        db_path_str=str(DB); back_str=str(BACK); exp_str=str(EXP)
        tk.Label(self.body,text=f"Database: {db_path_str}\nBackups: {back_str}\nExports: {exp_str}",bg="#f4f2f7",fg="#756d78",justify="left",font=("Segoe UI",9)).pack(anchor="w",pady=15)

    def restore_backup(self):
        """Restore a verified SQLite backup without leaving a partial database."""
        path=filedialog.askopenfilename(initialdir=BACK,title="Select backup",filetypes=[("SQLite backup","*.db")])
        if not path:
            return
        path=Path(path)
        if not _integrity_ok(path):
            messagebox.showerror("Restore blocked","The selected backup failed the SQLite integrity check.")
            return
        if not messagebox.askyesno("Restore Backup",
            "Your current database will be backed up before restore. Continue?"):
            return
        temp=DB.with_suffix(".restore.tmp.db")
        try:
            backup("before_restore")
            src=sqlite3.connect(path)
            dst=sqlite3.connect(temp)
            src.backup(dst)
            dst.close(); src.close()
            if not _integrity_ok(temp):
                raise RuntimeError("The temporary restored database failed integrity verification.")
            try: db.close()
            except Exception: pass
            os.replace(temp,DB)
            _switch_database(DB,self.company_name)
            self._ensure_upgrade_tables()
            self._sync_legacy_accounting()
            self.dashboard()
            messagebox.showinfo("Restored","Backup restored and verified successfully.")
        except Exception as exc:
            try: temp.unlink(missing_ok=True)
            except Exception: pass
            # Re-open the existing database if restore failed before replacement.
            try:
                if not db or not db.execute("SELECT 1").fetchone():
                    _switch_database(DB,self.company_name)
            except Exception:
                pass
            messagebox.showerror("Restore failed",str(exc))

    def csv(self):
        path=filedialog.asksaveasfilename(initialdir=EXP,defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path:return
        d,sp,rev,cog,prof,other_exp,net_profit,sale_cogs=calc()
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f)
            w.writerow(["SMART INVENTORY - COMPLETE EXPORT"])
            w.writerow(["Metric","Value"])
            for k,v in [("Purchase Expenditure",sp),("Sales Revenue",rev),("Cost of Goods Sold",cog),("Trading Profit",prof),("Other Expenditure",other_exp),("Net Profit",net_profit)]: w.writerow([k,v])
            w.writerow([])
            w.writerow(["PURCHASES"]); w.writerow(["AD Date","B.S. Date","Invoice","Vendor","PAN","Product","Quantity","Unit","Unit Cost","Total"])
            for p in db.execute("select * from purchases order by date,created,id"): w.writerow([p["date"],p["bs_date"] or ad_to_bs(p["date"]),p["invoice"],p["vendor"],p["pan"],p["product"],p["qty"],p["unit"] or "pcs",p["price"],p["qty"]*p["price"]])
            w.writerow([]); w.writerow(["SALES"]); w.writerow(["AD Date","B.S. Date","Invoice","Customer","Product","Quantity","Unit","Selling Price","Revenue","Cost of Goods Sold","Profit","Payment Status","Paid","Due Date"])
            for s in db.execute("select * from sales order by date,created,id"):
                c=sale_cogs.get(s["id"],0.0); revenue=s["qty"]*s["price"]; w.writerow([s["date"],s["bs_date"] or ad_to_bs(s["date"]),s["invoice"],s["customer"],s["product"],s["qty"],s["unit"] or "pcs",s["price"],revenue,c,revenue-c,s["payment_status"],s["paid"],s["due_date"]])
            w.writerow([]); w.writerow(["EXPENDITURES"]); w.writerow(["AD Date","B.S. Date","Category","Description","Amount"])
            for x in db.execute("select * from expenditures order by date,created,id"): w.writerow([x["date"],x["bs_date"] or ad_to_bs(x["date"]),x["category"],x["description"],x["amount"]])
            w.writerow([]); w.writerow(["STOCK SUMMARY"]); w.writerow(["Product","Unit","Purchased","Sold","Stock","Avg Cost","Stock Value"])
            for r in d.values(): w.writerow([r[0],r[1],r[2],r[3],r[6],r[5],max(0,r[6])*r[5]])
        messagebox.showinfo("Exported","Complete CSV exported successfully.")
    def creator(self):
        self.clear()
        f=tk.Frame(self.body,bg="white")
        f.pack(fill="both",expand=True)

        card=tk.Frame(f,bg="#fbf8fa",highlightbackground="#eadfe5",highlightthickness=1)
        card.pack(pady=55,padx=40,fill="x")

        try:
            self.creator_photo=tk.PhotoImage(file=str(resource_path("creator_cat.png")))
            tk.Label(card,image=self.creator_photo,bg="#fbf8fa").pack(pady=(28,14))
        except Exception:
            tk.Label(card,text="CREATOR",bg="#f8d7e4",fg="#8f244e",
                     font=("Segoe UI",24,"bold"),padx=28,pady=18).pack(pady=(28,14))

        tk.Label(card,text="CREATOR",bg="#fbf8fa",fg="#6f6875",
                 font=("Segoe UI",9,"bold")).pack()
        tk.Label(card,text="Smart Inventory",bg="#fbf8fa",
                 font=("Segoe UI",26,"bold")).pack(pady=5)
        tk.Label(card,text="Created by Bhawesh Mishra",bg="#fbf8fa",
                 font=("Segoe UI",16,"bold")).pack()
        tk.Label(card,text="Offline inventory • No cloud • No subscription",
                 bg="#fbf8fa",fg="#18794e").pack(pady=(10,28))
    def _toggle_company_menu(self):
        """Toggle company dropdown menu."""
        if self._menu_open:
            self._close_company_menu()
        else:
            self._open_company_menu()
    
    def _open_company_menu(self):
        """Open an in-app company switcher overlay.

        The switcher is deliberately a child Frame of the main window rather
        than an overrideredirect Toplevel. This keeps it inside a maximized or
        fullscreen application and prevents the old popup from escaping the
        application bounds on Windows.
        """
        try:
            con=_auth_conn()
            companies=con.execute(
                "SELECT id,name,db_path FROM companies ORDER BY lower(name)"
            ).fetchall()
            con.close()
        except Exception as e:
            messagebox.showerror("Error",f"Could not load companies:\n{e}",parent=self)
            return

        if not companies:
            messagebox.showinfo("No Companies","No companies found.\nCreate one first.",parent=self)
            return

        self._close_company_menu()
        self.update_idletasks()

        # Full-window scrim. Everything remains inside the application.
        overlay=tk.Frame(self,bg="#111018")
        overlay.place(relx=0,rely=0,relwidth=1,relheight=1)
        overlay.lift()
        self._company_menu=overlay

        # Prevent accidental clicks from reaching the application underneath.
        overlay.bind("<Button-1>",lambda e: "break")

        # Main modal card.
        card=tk.Frame(overlay,bg="#fbf9fc",highlightbackground="#d7d0da",
                      highlightthickness=1)
        card.place(relx=.5,rely=.5,anchor="center",relwidth=.58,relheight=.76)

        # Header
        header=tk.Frame(card,bg="#1e1b24",height=92)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_wrap=tk.Frame(header,bg="#1e1b24")
        title_wrap.pack(side="left",fill="both",expand=True,padx=28,pady=16)
        tk.Label(title_wrap,text="SWITCH COMPANY",bg="#1e1b24",fg="white",
                 font=("Segoe UI",16,"bold")).pack(anchor="w")
        tk.Label(title_wrap,text="Choose the business workspace you want to open",
                 bg="#1e1b24",fg="#aaa2ad",font=("Segoe UI",9)).pack(anchor="w",pady=(3,0))

        badge=tk.Frame(header,bg="#302a34")
        badge.pack(side="right",padx=22)
        tk.Label(badge,text=str(len(companies)),bg="#302a34",fg="#f08ab0",
                 font=("Segoe UI",13,"bold"),padx=12,pady=5).pack()
        tk.Label(badge,text="COMPANIES",bg="#302a34",fg="#8d8591",
                 font=("Segoe UI",7,"bold"),padx=8,pady=2).pack()

        # Scrollable list area
        body=tk.Frame(card,bg="#f5f2f7")
        body.pack(fill="both",expand=True)

        canvas=tk.Canvas(body,bg="#f5f2f7",highlightthickness=0,bd=0)
        scrollbar=tk.Scrollbar(body,orient="vertical",command=canvas.yview,
                               relief="flat",bd=0,width=8)
        list_frame=tk.Frame(canvas,bg="#f5f2f7")
        window_id=canvas.create_window((0,0),window=list_frame,anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left",fill="both",expand=True,padx=(18,0),pady=16)
        scrollbar.pack(side="right",fill="y",padx=(0,14),pady=16)

        def resize_list(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id,width=canvas.winfo_width())
        list_frame.bind("<Configure>",resize_list)
        canvas.bind("<Configure>",resize_list)

        def switch_handler(cid,cname,cpath,event=None):
            self._do_switch_company(cid,cname,cpath)

        for comp in companies:
            cid, cname, cpath = comp["id"], comp["name"], comp["db_path"]
            current=(cname==self.company_name)

            row=tk.Frame(list_frame,bg="#ffffff" if not current else "#fff0f5",
                         highlightbackground="#ddd5df" if not current else "#c83d73",
                         highlightthickness=1,cursor="hand2")
            row.pack(fill="x",pady=5,padx=4)

            accent=tk.Frame(row,bg="#c83d73" if current else "#e5dfe7",width=5)
            accent.pack(side="left",fill="y")

            content=tk.Frame(row,bg=row.cget("bg"))
            content.pack(side="left",fill="both",expand=True,padx=18,pady=14)

            top=tk.Frame(content,bg=row.cget("bg"))
            top.pack(fill="x")
            tk.Label(top,text=cname,bg=row.cget("bg"),fg="#24202a",
                     font=("Segoe UI",11,"bold"),anchor="w").pack(side="left",fill="x",expand=True)

            if current:
                tk.Label(top,text="CURRENT",bg="#c83d73",fg="white",
                         font=("Segoe UI",7,"bold"),padx=9,pady=4).pack(side="right")

            tk.Label(content,
                     text="Currently selected workspace" if current else "Click to switch to this workspace",
                     bg=row.cget("bg"),fg="#817784",font=("Segoe UI",8),anchor="w"
                     ).pack(anchor="w",pady=(4,0))

            if not current and len(companies)>1:
                def delete_handler(cid=cid,cname=cname,cpath=cpath):
                    self._delete_company(cid,cname,cpath)
                del_btn=tk.Button(content,text="Delete company",command=delete_handler,
                                  bg="#f6f1f4",fg="#8b7782",activebackground="#fbe8ee",
                                  activeforeground="#b52f61",bd=0,font=("Segoe UI",8,"bold"),
                                  padx=9,pady=4,cursor="hand2")
                del_btn.pack(anchor="e",pady=(5,0))
                del_btn.bind("<Button-1>",lambda e: "break")

            # Bind only non-delete descendants to switch.
            row.bind("<Button-1>",lambda e,cid=cid,cname=cname,cpath=cpath:switch_handler(cid,cname,cpath,e))
            for w in (content,top):
                w.bind("<Button-1>",lambda e,cid=cid,cname=cname,cpath=cpath:switch_handler(cid,cname,cpath,e))

            def hover_enter(e,row=row,current=current):
                if not current:
                    row.configure(bg="#fcf9fb")
                    for child in row.winfo_children():
                        if isinstance(child,tk.Frame):
                            try: child.configure(bg="#fcf9fb")
                            except Exception: pass
            def hover_leave(e,row=row,current=current):
                if not current:
                    row.configure(bg="#ffffff")
                    for child in row.winfo_children():
                        if isinstance(child,tk.Frame):
                            try: child.configure(bg="#ffffff")
                            except Exception: pass
            row.bind("<Enter>",hover_enter)
            row.bind("<Leave>",hover_leave)

        # Footer actions
        footer=tk.Frame(card,bg="#ffffff",height=68)
        footer.pack(fill="x",side="bottom")
        footer.pack_propagate(False)
        tk.Frame(footer,bg="#e5dfe7",height=1).pack(fill="x")

        tk.Button(footer,text="＋  Create New Company",command=lambda:(self._close_company_menu(),self._create_company_quick()),
                  bg="#c83d73",fg="white",activebackground="#ad315f",activeforeground="white",
                  bd=0,font=("Segoe UI",9,"bold"),padx=15,pady=8,cursor="hand2").pack(side="left",padx=(22,8),pady=12)
        tk.Button(footer,text="Close",command=self._close_company_menu,
                  bg="#eee9ef",fg="#403843",activebackground="#e3dce5",
                  bd=0,font=("Segoe UI",9,"bold"),padx=16,pady=8,cursor="hand2").pack(side="right",padx=22,pady=12)

        # Keyboard support and focus. Escape always closes the in-app overlay.
        self._menu_open=True
        self.bind("<Escape>",self._company_escape,add="+")
        try:
            card.focus_set()
        except Exception:
            pass

    def _company_escape(self,event=None):
        if getattr(self,"_menu_open",False):
            self._close_company_menu()
            return "break"

    def _schedule_close_check(self):
        """Schedule a check to close menu if focus moved away."""
        self._close_check_id = self.after(100, self._check_and_close_menu)
    
    def _cancel_close_check(self):
        """Cancel any pending close-check callback."""
        cid = getattr(self, '_close_check_id', None)
        if cid is not None:
            self.after_cancel(cid)
            self._close_check_id = None
    
    def _check_and_close_menu(self):
        """Check if menu should be closed."""
        if not self._menu_open or not self._company_menu:
            return
        
        try:
            # Check if mouse is over menu
            x=self.winfo_pointerx()
            y=self.winfo_pointery()
            
            mx=self._company_menu.winfo_rootx()
            my=self._company_menu.winfo_rooty()
            mw=self._company_menu.winfo_width()
            mh=self._company_menu.winfo_height()
            
            if mx<=x<=mx+mw and my<=y<=my+mh:
                return
            
            # Mouse is outside - close
            self._close_company_menu()
        except Exception:
            self._close_company_menu()
    
    def _close_company_menu(self):
        """Close the in-app company switcher overlay."""
        self._cancel_close_check()
        try:
            if self._company_menu and self._company_menu.winfo_exists():
                self._company_menu.destroy()
        except Exception:
            pass
        finally:
            self._company_menu=None
            self._menu_open=False
            try:
                self.unbind("<Escape>")
            except Exception:
                pass
    
    def _do_switch_company(self, company_id, company_name, db_path):
        """Execute company switch."""
        # Close menu first
        self._close_company_menu()
        
        if company_name==self.company_name:
            return
        
        # Confirm with user
        if not messagebox.askyesno("Switch Company",
            f"Switch to '{company_name}'?\n\nAny unsaved form data will be lost.",
            parent=self):
            return
        
        try:
            backup("before_quick_switch")
        except Exception:
            pass
        
        try:
            # Switch database
            _switch_database(db_path, company_name)
            
            # Ensure upgrade tables (products_master, customers, etc.) exist
            self._ensure_upgrade_tables()
            self._sync_legacy_accounting()
            
            # Update state
            self.company_name=company_name
            
            # Update UI
            self.title(f"Smart Inventory — {company_name}")
            self.company_btn.configure(text=f"◉  {company_name}  ▾")
            
            # Update sidebar
            self._update_sidebar_company(company_name)
            
            # Refresh dashboard
            self.dashboard()
            
            messagebox.showinfo("Company Switched",
                              f"Now working with: {company_name}",
                              parent=self)
        except Exception as exc:
            messagebox.showerror("Switch Failed",
                               f"Could not switch to {company_name}:\n\n{exc}",
                               parent=self)
    
    def _delete_company(self, company_id, company_name, db_path):
        """Delete a company and its data."""
        # Prevent deleting current company
        if company_name==self.company_name:
            messagebox.showwarning("Cannot Delete",
                f"Cannot delete '{company_name}' because it is currently active.\n\n"
                "Please switch to another company first.",
                parent=self)
            return
        
        # Count companies to check if this is the last one
        try:
            con=_auth_conn()
            count=con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            con.close()
            
            if count <= 1:
                messagebox.showwarning("Cannot Delete",
                    "This is the only remaining company.\n"
                    "You cannot delete all companies. Create another one first.",
                    parent=self)
                return
        except Exception:
            pass
        
        # Strong confirmation dialog
        if not messagebox.askyesno(
            "⚠️ Delete Company",
            f"Are you sure you want to DELETE '{company_name}'?\n\n"
            "⚠️ This action CANNOT be undone!\n\n"
            "The following will be permanently deleted:\n"
            "• All purchase records\n"
            "• All sales records\n"
            "• All expenditure entries\n"
            "• All inventory data\n"
            "• The company database file",
            parent=self,
            icon="warning"
        ):
            return
        
        # Second confirmation for safety
        if not messagebox.askyesno(
            "Final Confirmation",
            f"Type 'DELETE' is not required, but please confirm:\n\n"
            f"Permanently delete '{company_name}' and ALL its data?",
            parent=self
        ):
            return
        
        try:
            con=_auth_conn()
            
            # Get db_path from DB in case it differs
            row=con.execute("SELECT db_path FROM companies WHERE id=?",(company_id,)).fetchone()
            actual_db_path=row["db_path"] if row else db_path
            
            # Delete company record from auth database
            con.execute("DELETE FROM users WHERE company_id=?",(company_id,))
            con.execute("DELETE FROM companies WHERE id=?",(company_id,))
            con.commit()
            con.close()
            
            # Try to delete the database file
            import os as _os
            try:
                if actual_db_path and _os.path.exists(actual_db_path):
                    _os.remove(actual_db_path)
                    
                    # Also try to delete backups folder if exists
                    backup_dir=Path(actual_db_path).parent/"backups"
                    if backup_dir.exists():
                        import shutil as _shutil
                        _shutil.rmtree(backup_dir, ignore_errors=True)
                    
                    # Also try to delete exports folder
                    export_dir=Path(actual_db_path).parent/"exports"
                    if export_dir.exists():
                        import shutil as _shutil
                        _shutil.rmtree(export_dir, ignore_errors=True)
            except Exception as file_err:
                # File deletion failed but DB record is deleted - that's OK
                print(f"Warning: Could not delete database file: {file_err}")
            
            # Show success message
            messagebox.showinfo("Company Deleted",
                f"'{company_name}' has been deleted successfully.\n\n"
                "All associated data has been removed.",
                parent=self)
            
            # Close menu and refresh
            self._close_company_menu()
            
        except Exception as exc:
            messagebox.showerror("Delete Failed",
                f"Could not delete '{company_name}':\n\n{exc}",
                parent=self)
    
    def _update_sidebar_company(self, company_name):
        """Update the company name display in sidebar."""
        try:
            for child in self.sidebar.winfo_children():
                if isinstance(child,tk.Frame) and str(child.cget("bg"))=="#2a2530":
                    for subchild in child.winfo_children():
                        if isinstance(subchild,tk.Label) and subchild.cget("fg")=="white":
                            subchild.configure(text=company_name)
                            break
                    break
        except Exception:
            pass
    
    def _create_company_quick(self):
        """Quick create new company dialog."""
        d=tk.Toplevel(self); d.title("Create New Company"); d.geometry("500x300"); d.minsize(460,280)
        d.configure(bg="white"); d.transient(self); d.grab_set()
        
        tk.Label(d,text="Create New Company",bg="white",fg="#1e1b24",
                font=("Segoe UI",16,"bold")).pack(pady=(30,8))
        tk.Label(d,text="A separate database will be created for this company.",bg="white",fg="#7a7080",
                font=("Segoe UI",9)).pack()
        
        frm=tk.Frame(d,bg="white"); frm.pack(fill="x",padx=40,pady=25)
        tk.Label(frm,text="COMPANY NAME",bg="white",fg="#554c58",
                font=("Segoe UI",9,"bold")).pack(anchor="w")
        name_var=tk.StringVar()
        entry=tk.Entry(frm,textvariable=name_var,font=("Segoe UI",11),bd=0,
                      bg="#f4f2f7",insertbackground="#c83d73")
        entry.pack(fill="x",pady=(6,0),ipady=8)
        tk.Frame(frm,bg="#e1d9e0",height=2).pack(fill="x")
        entry.focus_set()
        
        def save():
            name=name_var.get().strip()
            if not name:
                messagebox.showwarning("Create Company","Enter a company name.",parent=d); return
            con=_auth_conn()
            exists=con.execute("SELECT id FROM companies WHERE name=?",(name,)).fetchone()
            if exists:
                con.close(); messagebox.showerror("Create Company","That company already exists.",parent=d); return
            cid=con.execute("INSERT INTO companies(name,db_path,created) VALUES(?,?,?)",
                           (name,"",datetime.now().isoformat())).lastrowid
            safe=re.sub(r"[^A-Za-z0-9_-]+","_",name).strip("_") or f"company_{cid}"
            path=str(APP/f"{safe}.db")
            con.execute("UPDATE companies SET db_path=? WHERE id=?",(path,cid))
            con.commit(); con.close()
            _prepare_company_db(path,DB)
            d.destroy()
            self._do_switch_company(cid, name, path)
        
        btn_frm=tk.Frame(d,bg="white"); btn_frm.pack(pady=(10,25))
        tk.Button(btn_frm,text="CANCEL",command=d.destroy,bg="#ede8ee",fg="#302a33",
                 bd=0,font=("Segoe UI",9,"bold"),padx=18,pady=8,cursor="hand2").pack(side="right",padx=6)
        tk.Button(btn_frm,text="CREATE & SWITCH",command=save,bg="#c83d73",fg="white",
                 bd=0,font=("Segoe UI",9,"bold"),padx=18,pady=8,cursor="hand2").pack(side="right")

    def switch_company(self):
        if not messagebox.askyesno("Switch Company","Switch company? Any unsaved form data will be lost.",parent=self): return
        try: backup("before_switch_company")
        except Exception: pass
        try: db.close()
        except Exception: pass
        self.destroy()
        launch()

    def close(self):
        try: backup("on_close")
        except Exception: pass
        db.close(); self.destroy()

if __name__ == "__main__":
    launch()
