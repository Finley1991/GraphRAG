"""
贵州茅台(600519) 数据采集脚本
=================================
从新浪财经接口获取贵州茅台的 公告、研报、新闻 数据。

数据来源：
  - 公告: i.money.finance.sina.com.cn
  - 研报: i.stock.finance.sina.com.cn
  - 新闻: i.recommend.cj.sina.cn

数据存储:
  - SQLite 数据库: ./data/maotai_data.db
  - 公告 PDF:   ./data/gonggao/
  - 研报 PDF:   ./data/yanbao/

运行:
  python tests/fetch_maotai_data.py
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests

# ============================================================
# 0. 配置
# ============================================================

STOCK_CODE = "600519"          # 公告接口用，6位数字
STOCK_SYMBOL = "sh600519"      # 研报/新闻接口用，市场前缀+代码

START_DATE = "2025-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE_YMD = START_DATE.replace("-", "")
END_DATE_YMD = END_DATE.replace("-", "")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GONGGAO_DIR = DATA_DIR / "gonggao"
YANBAO_DIR = DATA_DIR / "yanbao"
DB_PATH = DATA_DIR / "maotai_data.db"

REQUEST_INTERVAL = 0.3
PAGE_SIZE = 20
REQUEST_TIMEOUT = 30


# ============================================================
# 1. 工具函数
# ============================================================

def clean_proxy():
    for key in [
        "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
        "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
    ]:
        os.environ.pop(key, None)


def get_session():
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return sess


def ensure_dirs():
    GONGGAO_DIR.mkdir(parents=True, exist_ok=True)
    YANBAO_DIR.mkdir(parents=True, exist_ok=True)


def clean_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")


def download_pdf(sess: requests.Session, url: str, save_dir: Path, filename: str = None) -> str | None:
    """下载 PDF，已存在则跳过。返回相对项目根目录的路径"""
    if not filename:
        name = url.rstrip("/").split("/")[-1]
        if not name or not name.lower().endswith(".pdf"):
            name = f"{uuid4().hex[:8]}.pdf"
        filename = name

    save_path = save_dir / filename
    if save_path.exists():
        if save_path.stat().st_size > 0:
            return str(save_path.relative_to(DATA_DIR.parent))
        # 空文件重新下载
        save_path.unlink()

    try:
        resp = sess.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
        size_mb = len(resp.content) / 1024 / 1024
        print(f"    [PDF] {filename} ({size_mb:.1f}MB)")
        return str(save_path.relative_to(DATA_DIR.parent))
    except Exception as e:
        print(f"    [WARN] PDF 下载失败: {e}")
        return None


# ============================================================
# 2. 数据库
# ============================================================

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            announcement_id TEXT UNIQUE,
            title           TEXT,
            declared_date   TEXT,
            ann_type        TEXT,
            level1          TEXT,
            source          TEXT,
            pdf_url         TEXT,
            pdf_local_path  TEXT,
            raw_json        TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS research_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id       TEXT UNIQUE,
            title           TEXT,
            report_date     TEXT,
            org_name        TEXT,
            author          TEXT,
            rating          TEXT,
            summary         TEXT,
            detail_url      TEXT,
            pdf_url         TEXT,
            pdf_local_path  TEXT,
            raw_json        TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id         TEXT UNIQUE,
            title           TEXT,
            news_date       TEXT,
            source          TEXT,
            news_url        TEXT,
            raw_json        TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            data_type       TEXT NOT NULL,
            page            INTEGER DEFAULT 0,
            fetched_count   INTEGER DEFAULT 0,
            total_count     INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'success',
            error_msg       TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    return conn


# ============================================================
# 3. 公告采集
# ============================================================

def fetch_announcements(sess: requests.Session, conn: sqlite3.Connection):
    print(f"\n{'='*60}")
    print(f"【公告】贵州茅台 {STOCK_CODE}")
    print(f"{'='*60}")

    api_url = "http://i.money.finance.sina.com.cn/corp/api/openapi.php/CB_AllService.getBulletinList"
    page = 1
    total_inserted = 0
    total_api = 0
    max_pages = 999

    while page <= max_pages:
        params = {
            "Display": PAGE_SIZE,
            "Page": page,
            "Type": "recommend_ai",
            "PaperCode": STOCK_CODE,
            "StartDate": START_DATE_YMD,
            "EndDate": END_DATE_YMD,
        }

        try:
            resp = sess.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
            result = body.get("result", {})
            data_wrapper = result.get("data", {})
            items = data_wrapper.get("data", [])
            otherinfo = data_wrapper.get("otherinfo", {})
        except Exception as e:
            print(f"  [ERROR] 第 {page} 页: {e}")
            _log_fetch(conn, "announcement", page, 0, total_api, "error", str(e))
            break

        if not items:
            print(f"  第 {page} 页无数据，结束")
            break

        # 第一页时显示总页数
        if page == 1:
            max_pages = int(otherinfo.get("page_count", 999))
            total_api = int(otherinfo.get("page_sign", 0)) * PAGE_SIZE or max_pages * PAGE_SIZE
            print(f"  共 {max_pages} 页")

        inserted = 0
        pre = conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]

        for item in items:
            ann_id = str(item.get("ID", ""))
            title = (item.get("title") or "").strip()
            date_val = (item.get("date") or "").strip()[:10]
            ann_type = (item.get("type") or "").strip()
            level1_str = (item.get("type2") or "").strip()
            source = (item.get("origin") or "").strip()
            pdf_url = (item.get("pdf_path") or "").strip()
            pdf_flag = item.get("pdf_flag", 0)

            pdf_local_path = None
            if pdf_flag == 1 and pdf_url:
                fname = f"{STOCK_CODE}_{ann_id}.PDF"
                pdf_local_path = download_pdf(sess, pdf_url, GONGGAO_DIR, fname)

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO announcements
                        (announcement_id, title, declared_date, ann_type, level1,
                         source, pdf_url, pdf_local_path, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ann_id, title, date_val, ann_type, level1_str,
                      source, pdf_url, pdf_local_path,
                      json.dumps(item, ensure_ascii=False)))
            except Exception as e:
                print(f"    [WARN] {ann_id}: {e}")

            inserted += 1

        conn.commit()
        real_inserted = conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] - pre

        total_inserted += real_inserted
        print(f"  第 {page:3d}/{max_pages} 页: {len(items)} 条, 新增 {real_inserted} 条")
        _log_fetch(conn, "announcement", page, len(items), total_api, "success", "")

        if page >= max_pages:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"  ✅ 公告完成, 共新增 {total_inserted} 条")


# ============================================================
# 4. 研报采集
# ============================================================

def fetch_research_reports(sess: requests.Session, conn: sqlite3.Connection):
    print(f"\n{'='*60}")
    print(f"【研报】贵州茅台 {STOCK_SYMBOL}")
    print(f"{'='*60}")

    api_url = "http://i.stock.finance.sina.com.cn/stock/api/openapi.php/ReportService.getList"
    page = 1
    total_inserted = 0
    total_api = 0
    max_pages = 999

    while page <= max_pages:
        params = {
            "kind": "lastest", "t1": 2,
            "num": PAGE_SIZE, "page": page,
            "symbol": STOCK_SYMBOL,
            "start_date": START_DATE, "end_date": END_DATE,
            "get_content_flag": 1,
        }

        try:
            resp = sess.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
            data_wrapper = body.get("result", {}).get("data", {})
            items = data_wrapper.get("data", [])
        except Exception as e:
            print(f"  [ERROR] 第 {page} 页: {e}")
            _log_fetch(conn, "research_report", page, 0, 0, "error", str(e))
            break

        if not items:
            print(f"  第 {page} 页无数据，结束")
            break

        if page == 1:
            total_api = int(data_wrapper.get("total", 0))
            max_pages = (total_api + PAGE_SIZE - 1) // PAGE_SIZE
            print(f"  共 {total_api} 条, {max_pages} 页")

        inserted = 0
        pre = conn.execute("SELECT COUNT(*) FROM research_reports").fetchone()[0]
        for item in items:
            report_id = str(item.get("report_id", ""))
            title = (item.get("title") or "").strip()
            date_val = (item.get("adddate") or "").strip()
            org = (item.get("orgname") or "").strip()
            author = (item.get("author") or "").strip()
            rating = (item.get("rating") or "").strip()
            summary = (item.get("reportinfo") or "").strip()
            detail_url = (item.get("detail_url") or "").strip()

            # 研报 API 不直接返回 PDF，存 detail_url 供后续抓取
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO research_reports
                        (report_id, title, report_date, org_name, author, rating,
                         summary, detail_url, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (report_id, title, date_val, org, author, rating,
                      summary, detail_url,
                      json.dumps(item, ensure_ascii=False)))
            except Exception as e:
                print(f"    [WARN] {report_id}: {e}")

            inserted += 1

        conn.commit()
        real_inserted = conn.execute("SELECT COUNT(*) FROM research_reports").fetchone()[0] - pre

        total_inserted += real_inserted
        print(f"  第 {page:3d}/{max_pages} 页: {len(items)} 条, 新增 {real_inserted} 条")
        _log_fetch(conn, "research_report", page, len(items), total_api, "success", "")

        if page >= max_pages:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"  ✅ 研报完成, 共新增 {total_inserted} 条")


# ============================================================
# 5. 新闻采集
# ============================================================

def fetch_news(sess: requests.Session, conn: sqlite3.Connection):
    print(f"\n{'='*60}")
    print(f"【新闻】贵州茅台 {STOCK_SYMBOL}")
    print(f"{'='*60}")

    api_url = "http://i.recommend.cj.sina.cn/app/v1/stock_news/get"
    page = 1
    total_inserted = 0
    ctime = ""
    docid = ""

    while True:
        params = {
            "market": "cn",
            "symbol": STOCK_SYMBOL,
            "page": page,
            "num": PAGE_SIZE,
            "chwm": "34020_0001", "wm": "b122",
            "from": "7049995012", "fr": "financeapp",
            "deviceid": "647916e9febbfc6b", "version": "8.8.0.1",
            "ctime": ctime, "docid": docid,
        }

        try:
            resp = sess.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
            items = body.get("result", {}).get("data", [])
        except Exception as e:
            print(f"  [ERROR] 第 {page} 页: {e}")
            _log_fetch(conn, "news", page, 0, 0, "error", str(e))
            break

        if not items:
            print(f"  第 {page} 页无数据，结束")
            break

        inserted = 0
        pre = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        for item in items:
            news_id = str(item.get("docid", ""))
            title = (item.get("title") or "").strip()
            date_val = (item.get("create_date") or "").strip()
            source = (item.get("media_source") or "").strip()
            news_url = (item.get("url") or "").strip()
            if not news_id:
                news_id = news_url or uuid4().hex

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO news
                        (news_id, title, news_date, source, news_url, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (news_id, title, date_val, source, news_url,
                      json.dumps(item, ensure_ascii=False)))
            except Exception as e:
                print(f"    [WARN] {news_id}: {e}")

            inserted += 1

            # 记录翻页游标
            if item.get("ctime"):
                ctime = str(item["ctime"])
            if item.get("docid"):
                docid = str(item["docid"])

        conn.commit()
        real_inserted = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] - pre

        total_inserted += real_inserted
        print(f"  第 {page:3d} 页: {len(items)} 条, 新增 {real_inserted} 条")
        _log_fetch(conn, "news", page, len(items), 0, "success", "")

        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"  ✅ 新闻完成, 共新增 {total_inserted} 条")


# ============================================================
# 6. 采集日志
# ============================================================

def _log_fetch(conn, data_type, page, fetched, total, status, error_msg):
    try:
        conn.execute(
            "INSERT INTO fetch_log (data_type, page, fetched_count, total_count, status, error_msg) VALUES (?, ?, ?, ?, ?, ?)",
            (data_type, page, fetched, total, status, error_msg),
        )
    except Exception:
        pass


# ============================================================
# 7. 主函数
# ============================================================

def main():
    print(f"=" * 60)
    print(f"  贵州茅台 ({STOCK_CODE}) 数据采集")
    print(f"  时间: {START_DATE} ~ {END_DATE}")
    print(f"  数据: {DATA_DIR}")
    print(f"=" * 60)

    clean_proxy()
    ensure_dirs()
    conn = init_db()
    sess = get_session()

    start = time.time()

    fetch_announcements(sess, conn)
    fetch_research_reports(sess, conn)
    fetch_news(sess, conn)

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"  汇总")
    print(f"{'='*60}")
    cur = conn.cursor()
    for table, label in [("announcements", "公告"), ("research_reports", "研报"), ("news", "新闻")]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {label}: {cur.fetchone()[0]} 条")
    # PDF 统计
    pdf_count = len(list(GONGGAO_DIR.glob("*.[Pp][Dd][Ff]")))
    print(f"  公告 PDF: {pdf_count} 个")
    print(f"\n  耗时: {elapsed:.1f}s")
    print(f"  DB: {DB_PATH}")
    print(f"{'='*60}")

    conn.close()
    sess.close()


if __name__ == "__main__":
    main()