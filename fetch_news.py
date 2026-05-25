"""
基金投资助手 — 新闻抓取模块
================================
数据源 (按优先级):
  1. 新浪财经 API     — 滚动新闻, 50条/次
  2. akshare 财新     — 深度财经, 100条/次
  3. Tushare Pro      — 备用 (需 Token)

特性:
  - 每个源独立重试 3 次
  - 自动板块归类 + 优先级标注
  - 去重合并
  - 输出 news-data.json
"""

import json, time, datetime, re, urllib.request, sys, io

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ═══════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════
# 优先从环境变量读取，兼容 CI / 本地
import os as _os
TUSHARE_TOKEN = _os.environ.get('TUSHARE_TOKEN', '5f9253df50265b4eb013e091f248af7f8872a589e4635e66a00de775')
RETRY_COUNT = 3
RETRY_DELAY = 2  # 秒

SECTORS_KW = {
    '能源': ['能源','煤炭','石油','电力','光伏','锂电','储能','风电','氢能','OPEC','原油','天然气'],
    '黄金': ['黄金','贵金属','金价','避险','现货金','COMEX','央行购金'],
    '有色': ['有色','铜','铝','稀土','锂矿','钴','镍','锌','钨','碳酸锂','工业金属'],
    '半导体': ['半导体','芯片','光刻','晶圆','封装','EDA','HBM','先进制程','英伟达','台积电','中芯'],
    '光模块': ['光模块','CPO','光通信','800G','1.6T','硅光','光芯片','中际旭创','新易盛','天孚通信'],
    '机器人': ['机器人','具身智能','人形','自动化','伺服','减速器','传感器','Optimus','优必选'],
    '消费': ['消费','白酒','食品','家电','汽车','旅游','餐饮','零售','茅台','五粮液','比亚迪'],
    '医药': ['医药','创新药','CRO','器械','生物','疫苗','CXO','百济神州','药明','PD-1','ADC','GLP-1'],
    '金融': ['银行','券商','保险','金融','地产','REITs','分红','回购','增持','降息','利率'],
    'AI': ['AI','大模型','算力','GPU','ChatGPT','生成式','智能体','Agent','DeepSeek','文心','通义'],
}

HIGH_KW = ['央行','降息','加息','降准','MLF','LPR','美联储','监管','爆雷','清盘','崩盘','暴跌',
           '大涨','突破','政策','北向','外资','净流入','涨停','跌停','退市','罚款','处罚',
           '万亿','千亿','重磅','历史新高','紧急','突发','刚刚']
MED_KW = ['板块','行业','指数','基金','ETF','分红','净值','重仓','季报','年报','业绩','调研',
          '评级','策略','研报','龙头','主力','机构','私募','公募']

def classify_priority(title, content=''):
    text = title + ' ' + (content or '')
    for kw in HIGH_KW:
        if kw in text: return 'high'
    for kw in MED_KW:
        if kw in text: return 'medium'
    return 'low'

def classify_sectors(title):
    matched = []
    for sector, keywords in SECTORS_KW.items():
        for kw in keywords:
            if kw in title:
                matched.append(sector)
                break
    return matched if matched else ['综合']

def period_from_ts(ts):
    try: ts = int(ts)
    except: ts = 0
    if ts == 0: return 'night'
    h = datetime.datetime.fromtimestamp(ts).hour
    if 6 <= h < 12: return 'morning'
    if 12 <= h < 18: return 'noon'
    return 'night'

def fmt_time(ts):
    try: ts = int(ts)
    except: return '--:--'
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M')

def fmt_date(ts):
    try: ts = int(ts)
    except: return '----'
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')

# ═══════════════════════════════════════════════════
#  重试装饰器
# ═══════════════════════════════════════════════════
def with_retry(name, fn):
    """执行 fn()，失败重试 RETRY_COUNT 次"""
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            result = fn()
            if result:
                print(f'  [{name}] ✓ {len(result)} 条')
                return result
            else:
                print(f'  [{name}] 第{attempt}次: 无数据')
        except Exception as e:
            print(f'  [{name}] 第{attempt}次失败: {e}')
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_DELAY)
    print(f'  [{name}] ✗ 全部失败')
    return []

# ═══════════════════════════════════════════════════
#  数据源 1: 新浪财经
# ═══════════════════════════════════════════════════
def fetch_sina():
    url = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=50&page=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    items = data.get('result', {}).get('data', [])
    results = []
    for item in items:
        title = re.sub(r'<[^>]*>', '', (item.get('title', '') or '').strip())
        if not title: continue
        ctime = item.get('ctime', 0)
        results.append({
            'title': title,
            'source': item.get('media_name', '新浪财经'),
            'url': item.get('url') or item.get('wapurl', ''),
            'content': (item.get('intro', '') or '')[:200],
            'priority': classify_priority(title, item.get('intro', '')),
            'sectors': classify_sectors(title),
            'period': period_from_ts(ctime),
            'date': fmt_date(ctime),
            'time': fmt_time(ctime),
            'keywords': (item.get('keywords', '') or '').split(',') if item.get('keywords') else [],
        })
    return results

# ═══════════════════════════════════════════════════
#  数据源 2: akshare 财新
# ═══════════════════════════════════════════════════
def fetch_caixin():
    import akshare as ak
    df = ak.stock_news_main_cx()
    results = []
    for _, row in df.iterrows():
        tag = str(row.get('tag', '') or '')
        summary = str(row.get('summary', '') or '')
        title = summary[:80] if summary else tag
        if not title or len(title) < 8: continue
        results.append({
            'title': title,
            'source': '财新',
            'url': row.get('url', ''),
            'content': summary[:200],
            'priority': classify_priority(title, summary),
            'sectors': classify_sectors(title),
            'period': 'noon',
            'date': datetime.date.today().isoformat(),
            'time': '--:--',
            'keywords': [tag] if tag else [],
        })
    return results

# ═══════════════════════════════════════════════════
#  数据源 3: Tushare Pro
#  接口文档: https://tushare.pro/document/2?doc_id=143
#  支持的 src: sina, wallstreetcn, eastmoney, 10jqka, yuncaijing, fenghuang
# ═══════════════════════════════════════════════════
def fetch_tushare():
    if not TUSHARE_TOKEN:
        print('  [Tushare] 未配置 Token，跳过')
        return []
    import tushare as ts
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    # 只调用 1 个源 (sina)，节省积分
    # 积分有限，不跑 wallstreetcn/eastmoney/10jqka
    try:
        df = pro.news(src='sina')
        if df is None or len(df) == 0: return []

        results = []
        for _, row in df.iterrows():
            content = str(row.get('content', '') or '')
            title = str(row.get('title', '') or '')
            if not title or title == 'None' or len(title) < 6:
                title = content[:60].strip()
            if not title or len(title) < 6: continue

            dt = str(row.get('datetime', '') or '')
            date = dt[:10] if len(dt) >= 10 else datetime.date.today().isoformat()
            tm = dt[11:16] if len(dt) >= 16 else '--:--'

            results.append({
                'title': title[:100],
                'source': 'Tushare-sina',
                'url': '',
                'content': content[:200],
                'priority': classify_priority(title, content),
                'sectors': classify_sectors(title),
                'period': 'noon',
                'date': date,
                'time': tm,
                'keywords': [],
            })
            if len(results) >= 50: break

        return results
    except Exception as e:
        print(f'    [Tushare] ✗ {str(e)[:60]}')
        return []

# ═══════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════
def main():
    print(f'--- 新闻抓取开始 ({datetime.datetime.now().strftime("%H:%M:%S")}) ---')

    all_news = []

    # 数据源 1: 新浪财经
    print('[源1] 新浪财经 API')
    all_news.extend(with_retry('新浪财经', fetch_sina))

    # 数据源 2: akshare 财新
    print('[源2] akshare 财新')
    all_news.extend(with_retry('财新', fetch_caixin))

    # 数据源 3: Tushare
    if TUSHARE_TOKEN:
        print('[源3] Tushare Pro')
        all_news.extend(with_retry('Tushare', fetch_tushare))

    # 去重
    seen = set()
    unique = []
    for n in all_news:
        key = n['title'][:40]
        if key not in seen:
            seen.add(key)
            unique.append(n)

    # 排序: 高优 → 中优 → 低优
    unique.sort(key=lambda x: (0 if x['priority']=='high' else 1 if x['priority']=='medium' else 2))

    # 输出
    output = {
        'updated': datetime.datetime.now().isoformat(),
        'total': len(unique),
        'sources': ['新浪财经', 'akshare-财新'] + (['Tushare'] if TUSHARE_TOKEN else []),
        'priority_dist': {
            'high': sum(1 for n in unique if n['priority']=='high'),
            'medium': sum(1 for n in unique if n['priority']=='medium'),
            'low': sum(1 for n in unique if n['priority']=='low'),
        },
        'items': unique,
    }

    # CI 环境用相对路径，本地用绝对路径
    import os
    outpath = os.environ.get('NEWS_OUTPUT_PATH', 'C:/Users/16204/fund-assistant/news-data.json')
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'--- 完成: {len(unique)} 条 (高优{output["priority_dist"]["high"]} 中优{output["priority_dist"]["medium"]} 低优{output["priority_dist"]["low"]}) → {outpath} ---')
    return output

if __name__ == '__main__':
    main()
