"""
Shared Platform Configs — 统一平台配置

供 app.py (网页抓取) 和 douyin_crawler (商品采集) 共享使用。
加新平台只需在此文件加一条配置，两边自动生效。
"""

import re

# ==============================
# 平台 → URL 域名映射（用于自动检测）
# ==============================
URL_DOMAIN_MAP = {
    'douyin.com':            'douyin',
    'www.douyin.com':        'douyin',
    'kuaishou.com':          'kuaishou',
    'www.kuaishou.com':      'kuaishou',
    'xiaohongshu.com':       'xiaohongshu',
    'www.xiaohongshu.com':   'xiaohongshu',
    'bilibili.com':          'bilibili',
    'www.bilibili.com':      'bilibili',
    'weibo.com':             'weibo',
    'www.weibo.com':         'weibo',
    'weixin.qq.com':         'shipinhao',
    'channels.weixin.qq.com':'shipinhao',
}

URL_PATH_PATTERNS = [
    # 内容平台
    (r'douyin\.com/video/',         'douyin'),
    (r'douyin\.com/note/',          'douyin'),
    (r'kuaishou\.com/short-video/', 'kuaishou'),
    (r'kuaishou\.com/photo/',       'kuaishou'),
    (r'xiaohongshu\.com/explore/',  'xiaohongshu'),
    (r'xiaohongshu\.com/discovery/', 'xiaohongshu'),
    (r'bilibili\.com/video/',       'bilibili'),
    (r'bilibili\.com/BV',           'bilibili'),
    (r'weibo\.com/\d+/\w+',        'weibo'),
    (r'channels\.weixin\.qq\.com/', 'shipinhao'),
    # 电商平台
    (r'douyin\.com/product/',       'douyin_mall'),
    (r'kuaishou\.com/product/',     'kuaishou_mall'),
    (r'xiaohongshu\.com/product/',  'xhs_mall'),
    (r'taobao\.com/item/',          'taobao'),
    (r'tmall\.com/item/',           'tmall'),
    (r'jd\.com/product/',           'jd'),
    (r'item\.jd\.com/',             'jd'),
    (r'pinduoduo\.com/.*product',  'pdd'),
    (r'yangkeduo\.com/.*product',  'pdd'),
    (r'1688\.com/offer/',           'ali1688'),
]

URL_DOMAIN_MAP = {
    'douyin.com':            None,  # 走路径匹配
    'www.douyin.com':        None,
    'kuaishou.com':          None,
    'www.kuaishou.com':      None,
    'xiaohongshu.com':       None,
    'www.xiaohongshu.com':   None,
    'bilibili.com':          'bilibili',
    'www.bilibili.com':      'bilibili',
    'weibo.com':             'weibo',
    'www.weibo.com':         'weibo',
    'weixin.qq.com':         'shipinhao',
    'channels.weixin.qq.com':'shipinhao',
    # 电商域名
    'taobao.com':            'taobao',
    'www.taobao.com':        'taobao',
    'tmall.com':             'tmall',
    'www.tmall.com':         'tmall',
    'jd.com':                'jd',
    'www.jd.com':            'jd',
    'item.jd.com':           'jd',
    'pinduoduo.com':         'pdd',
    'www.pinduoduo.com':     'pdd',
    'yangkeduo.com':         'pdd',
    '1688.com':              'ali1688',
    'www.1688.com':          'ali1688',
}


def auto_detect_platform(url: str) -> str | None:
    """从URL自动识别所属平台"""
    url = url.strip().lower()
    # 1. 路径模式匹配（优先级高：可区分video/product）
    for pattern, platform in URL_PATH_PATTERNS:
        if re.search(pattern, url):
            return platform
    # 2. 域名匹配
    for domain, platform in URL_DOMAIN_MAP.items():
        if platform and domain in url:
            return platform
    return None


# ==============================
# 统一 JS 提取器脚本
# ==============================
# data_extract: 每个平台只需配置 JSON_PATH 规则
# 格式: [{key, label, path, fallback}]
UNIFIED_EXTRACTOR_JS = """
function smartExtractByPaths(dataExtractRules) {
    const result = {};
    dataExtractRules.forEach(function(rule) {
        try {
            var val = rule.path.split('.').reduce(function(obj, key) {
                return (obj && obj[key] !== undefined && obj[key] !== null) ? obj[key] : undefined;
            }, window);
            if (val !== undefined && val !== null) {
                result[rule.key] = typeof val === 'object' ? JSON.stringify(val) : String(val);
            } else if (rule.fallback) {
                var fallbackFn = new Function('return ' + rule.fallback);
                var fb = fallbackFn();
                if (fb !== undefined) result[rule.key] = String(fb);
            }
        } catch(e) {}
    });
    return JSON.stringify(result);
}
"""


def make_extractor_js(data_extract: list[dict]) -> str:
    """生成带具体规则的统一提取器 JS"""
    import json
    rules_json = json.dumps(data_extract, ensure_ascii=False)
    return f"""
    (function() {{
        {UNIFIED_EXTRACTOR_JS}
        return smartExtractByPaths({rules_json});
    }})()
    """


# ==============================
# 网页抓取 — 平台预设 (Web Scraping)
# ==============================

# 每个平台配 data_extract (JSON_PATH规则) 替代传统 js_extract 字符串
# fallback 是降级DOM提取函数 (字符串形式的函数体)

PLATFORM_PRESETS = {
    # ========== 抖音 ==========
    'douyin': {
        'name': '抖音',
        'icon': '🎵',
        'color': '#161823',
        'homepage': 'https://www.douyin.com',
        'login_url': 'https://www.douyin.com/login',
        'note': '推荐用 Playwright 模式 + 登录浏览器抓取',
        'fields': [
            {'key': 'title',    'label': '视频标题',   'auto': True},
            {'key': 'author',   'label': '作者昵称',   'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
            {'key': 'shares',   'label': '转发/收藏数','auto': True},
            {'key': 'desc',     'label': '视频描述',   'auto': True},
            {'key': 'duration', 'label': '视频时长',   'auto': True},
        ],
        'data_extract': [
            {'key': 'title',    'label': '视频标题',   'path': '__INITIAL_STATE__.aweme.detail.desc',          'fallback': "document.querySelector('title')?.textContent?.replace(' - 抖音','')?.trim()"},
            {'key': 'author',   'label': '作者昵称',   'path': '__INITIAL_STATE__.aweme.detail.author.nickname', 'fallback': "document.querySelector('[class*=author],[class*=nickname]')?.textContent?.trim()"},
            {'key': 'likes',    'label': '点赞数',     'path': '__INITIAL_STATE__.aweme.detail.statistics.digg_count', 'fallback': None},
            {'key': 'comments', 'label': '评论数',     'path': '__INITIAL_STATE__.aweme.detail.statistics.comment_count', 'fallback': None},
            {'key': 'shares',   'label': '转发/收藏数','path': '__INITIAL_STATE__.aweme.detail.statistics.share_count', 'fallback': None},
            {'key': 'desc',     'label': '视频描述',   'path': '__INITIAL_STATE__.aweme.detail.desc',          'fallback': None},
            {'key': 'duration', 'label': '视频时长',   'path': '__INITIAL_STATE__.aweme.detail.duration',       'fallback': None},
        ],
        'api_patterns': ['/aweme/v1/web/aweme/detail/'],
    },

    # ========== 快手 ==========
    'kuaishou': {
        'name': '快手',
        'icon': '📷',
        'color': '#FF4906',
        'homepage': 'https://www.kuaishou.com',
        'login_url': 'https://www.kuaishou.com/login',
        'note': '推荐用 Playwright 模式 + 登录浏览器抓取',
        'fields': [
            {'key': 'title',    'label': '视频标题',   'auto': True},
            {'key': 'author',   'label': '作者昵称',   'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
            {'key': 'plays',    'label': '播放量',     'auto': True},
            {'key': 'desc',     'label': '视频描述',   'auto': True},
        ],
        'data_extract': [
            {'key': 'title',    'label': '视频标题', 'path': '__NUXT__.videoInfo.title',       'fallback': "document.querySelector('title')?.textContent"},
            {'key': 'author',   'label': '作者昵称', 'path': '__NUXT__.videoInfo.author.name',  'fallback': None},
            {'key': 'likes',    'label': '点赞数',   'path': '__NUXT__.videoInfo.likeCount',    'fallback': None},
            {'key': 'comments', 'label': '评论数',   'path': '__NUXT__.videoInfo.commentCount', 'fallback': None},
            {'key': 'plays',    'label': '播放量',   'path': '__NUXT__.videoInfo.viewCount',    'fallback': None},
            {'key': 'desc',     'label': '视频描述', 'path': '__NUXT__.videoInfo.caption',      'fallback': None},
        ],
    },

    # ========== 微信视频号 ==========
    'shipinhao': {
        'name': '微信视频号',
        'icon': '📹',
        'color': '#07C160',
        'homepage': 'https://channels.weixin.qq.com',
        'login_url': '',
        'note': '⚠️ 视频号只能在微信 App 内查看，网页版无法直接抓取。建议先用「登录」模式打开微信扫码登录。',
        'fields': [
            {'key': 'title',    'label': '视频标题',   'auto': True},
            {'key': 'author',   'label': '作者',       'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',    'label': '视频标题', 'path': '', 'fallback': "document.querySelector('h1,[class*=title]')?.textContent?.trim()"},
            {'key': 'author',   'label': '作者',     'path': '', 'fallback': "document.querySelector('[class*=author],[class*=nickname]')?.textContent?.trim()"},
            {'key': 'likes',    'label': '点赞数',   'path': '', 'fallback': None},
            {'key': 'comments', 'label': '评论数',   'path': '', 'fallback': None},
        ],
    },

    # ========== 小红书 ==========
    'xiaohongshu': {
        'name': '小红书',
        'icon': '📕',
        'color': '#FF2442',
        'homepage': 'https://www.xiaohongshu.com',
        'login_url': 'https://www.xiaohongshu.com/login',
        'note': '推荐登录后抓取，部分内容需要登录可见',
        'fields': [
            {'key': 'title',    'label': '笔记标题',   'auto': True},
            {'key': 'author',   'label': '作者昵称',   'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
            {'key': 'collects', 'label': '收藏数',     'auto': True},
            {'key': 'desc',     'label': '笔记内容',   'auto': True},
        ],
        'data_extract': [
            {'key': 'title',    'label': '笔记标题', 'path': '__INITIAL_STATE__.note.noteDetailMap', 'fallback': "document.querySelector('title')?.textContent?.replace(' - 小红书','')?.trim()"},
            {'key': 'author',   'label': '作者昵称', 'path': '__INITIAL_STATE__.note.noteDetailMap', 'fallback': None},
            {'key': 'likes',    'label': '点赞数',   'path': '', 'fallback': None},
            {'key': 'comments', 'label': '评论数',   'path': '', 'fallback': None},
            {'key': 'collects', 'label': '收藏数',   'path': '', 'fallback': None},
            {'key': 'desc',     'label': '笔记内容', 'path': '', 'fallback': "document.querySelector('meta[name=description]')?.getAttribute('content')"},
        ],
        'api_patterns': ['/api/sns/web/v1/feed', '/api/sns/web/v1/note'],
    },

    # ========== B站 ==========
    'bilibili': {
        'name': 'B站',
        'icon': '📺',
        'color': '#FB7299',
        'homepage': 'https://www.bilibili.com',
        'login_url': 'https://www.bilibili.com/login',
        'note': 'B站网页版数据结构稳定，JS注入提取效率最高',
        'fields': [
            {'key': 'title',    'label': '视频标题',   'auto': True},
            {'key': 'author',   'label': 'UP主',       'auto': True},
            {'key': 'plays',    'label': '播放量',     'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'coins',    'label': '硬币数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
            {'key': 'danmaku',  'label': '弹幕数',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',    'label': '视频标题', 'path': '__INITIAL_STATE__.videoData.title',       'fallback': "document.querySelector('title')?.textContent?.replace('_哔哩哔哩_bilibili','')?.trim()"},
            {'key': 'author',   'label': 'UP主',     'path': '__INITIAL_STATE__.videoData.owner.name',  'fallback': None},
            {'key': 'plays',    'label': '播放量',   'path': '__INITIAL_STATE__.videoData.stat.view',   'fallback': None},
            {'key': 'likes',    'label': '点赞数',   'path': '__INITIAL_STATE__.videoData.stat.like',   'fallback': None},
            {'key': 'coins',    'label': '硬币数',   'path': '__INITIAL_STATE__.videoData.stat.coin',   'fallback': None},
            {'key': 'comments', 'label': '评论数',   'path': '__INITIAL_STATE__.videoData.stat.reply',  'fallback': None},
            {'key': 'danmaku',  'label': '弹幕数',   'path': '__INITIAL_STATE__.videoData.stat.danmaku','fallback': None},
        ],
        'api_patterns': ['/x/web-interface/view', '/x/v2/medialist/resource/list'],
    },

    # ========== 微博 ==========
    'weibo': {
        'name': '微博',
        'icon': '🐦',
        'color': '#E6162D',
        'homepage': 'https://weibo.com',
        'login_url': 'https://weibo.com/login',
        'note': '微博数据以页面meta和DOM文本为主，建议登录后抓取',
        'fields': [
            {'key': 'content',  'label': '微博内容',   'auto': True},
            {'key': 'author',   'label': '博主昵称',   'auto': True},
            {'key': 'likes',    'label': '点赞数',     'auto': True},
            {'key': 'comments', 'label': '评论数',     'auto': True},
            {'key': 'reposts',  'label': '转发数',     'auto': True},
        ],
        'data_extract': [
            {'key': 'content',  'label': '微博内容', 'path': '', 'fallback': "document.querySelector('meta[name=description]')?.getAttribute('content')?.split('，')[0]"},
            {'key': 'author',   'label': '博主昵称', 'path': '', 'fallback': "document.querySelector('[class*=name],[class*=nickname]')?.textContent?.trim()"},
            {'key': 'likes',    'label': '点赞数',   'path': '', 'fallback': None},
            {'key': 'comments', 'label': '评论数',   'path': '', 'fallback': None},
            {'key': 'reposts',  'label': '转发数',   'path': '', 'fallback': None},
        ],
    },

    # ==============================
    # 电商平台（商品数据提取）
    # ==============================

    # ========== 抖音商城 ==========
    'douyin_mall': {
        'name': '抖音商城',
        'icon': '🛍️',
        'color': '#161823',
        'homepage': 'https://www.douyin.com',
        'login_url': 'https://www.douyin.com/login',
        'note': '提取抖音商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '售价',       'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '已售',       'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
            {'key': 'images',       'label': '商品图',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.productDetail.productInfo.title',         'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '售价',     'path': '__INITIAL_STATE__.productDetail.productInfo.price',        'fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__INITIAL_STATE__.productDetail.productInfo.marketPrice',   'fallback': None},
            {'key': 'sales',         'label': '已售',     'path': '__INITIAL_STATE__.productDetail.productInfo.sales',         'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__INITIAL_STATE__.productDetail.shopInfo.shopName',         'fallback': None},
            {'key': 'images',        'label': '商品图',   'path': '__INITIAL_STATE__.productDetail.productInfo.images',        'fallback': "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"},
        ],
        'api_patterns': ['/api/product/detail/', '/product/detail/'],
    },

    # ========== 快手商城 ==========
    'kuaishou_mall': {
        'name': '快手商城',
        'icon': '🛒',
        'color': '#FF4906',
        'homepage': 'https://www.kuaishou.com',
        'login_url': 'https://www.kuaishou.com/login',
        'note': '提取快手商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '售价',       'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '已售',       'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__NUXT__.productInfo.name',     'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '售价',     'path': '__NUXT__.productInfo.price',    'fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__NUXT__.productInfo.originalPrice', 'fallback': None},
            {'key': 'sales',         'label': '已售',     'path': '__NUXT__.productInfo.sales',    'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__NUXT__.productInfo.shopName', 'fallback': None},
        ],
    },

    # ========== 小红书商城 ==========
    'xhs_mall': {
        'name': '小红书商城',
        'icon': '🛍️',
        'color': '#FF2442',
        'homepage': 'https://www.xiaohongshu.com',
        'login_url': 'https://www.xiaohongshu.com/login',
        'note': '提取小红书商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '售价',       'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '已售',       'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.product.detail.title',     'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '售价',     'path': '__INITIAL_STATE__.product.detail.price',    'fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__INITIAL_STATE__.product.detail.originalPrice', 'fallback': None},
            {'key': 'sales',         'label': '已售',     'path': '__INITIAL_STATE__.product.detail.sales',    'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__INITIAL_STATE__.product.detail.shopName', 'fallback': None},
        ],
    },

    # ========== 淘宝 ==========
    'taobao': {
        'name': '淘宝',
        'icon': '🛒',
        'color': '#FF4400',
        'homepage': 'https://www.taobao.com',
        'login_url': 'https://www.taobao.com/login',
        'note': '提取淘宝商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '售价',       'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '累计销量',   'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
            {'key': 'rating',       'label': '评分',       'auto': True},
            {'key': 'comments',     'label': '评价数',     'auto': True},
            {'key': 'images',       'label': '商品图',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.detail.item.title',                    'fallback': "document.querySelector('title')?.textContent?.replace(/\\s*\\[.*?\\]\\s*/g,'')?.trim()"},
            {'key': 'price',         'label': '售价',     'path': '__INITIAL_STATE__.detail.api.item.priceHistory[0].price','fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__INITIAL_STATE__.detail.item.originalPrice',            'fallback': None},
            {'key': 'sales',         'label': '累计销量', 'path': '__INITIAL_STATE__.detail.item.totalSoldQuantity',        'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__INITIAL_STATE__.detail.seller.shopName',              'fallback': None},
            {'key': 'rating',        'label': '评分',     'path': '__INITIAL_STATE__.detail.item.rates',                   'fallback': None},
            {'key': 'comments',      'label': '评价数',   'path': '__INITIAL_STATE__.detail.item.commentCount',            'fallback': None},
            {'key': 'images',        'label': '商品图',   'path': '__INITIAL_STATE__.detail.api.item.images',               'fallback': "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"},
        ],
        'api_patterns': ['/detail/item/', '/api.item.detail'],
    },

    # ========== 天猫 ==========
    'tmall': {
        'name': '天猫',
        'icon': '🏬',
        'color': '#F04C25',
        'homepage': 'https://www.tmall.com',
        'login_url': 'https://www.tmall.com/login',
        'note': '提取天猫商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '售价',       'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '月销量',     'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
            {'key': 'comments',     'label': '评价数',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.item.detail.title',                 'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '售价',     'path': '__INITIAL_STATE__.item.detail.price',                 'fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__INITIAL_STATE__.item.detail.originalPrice',          'fallback': None},
            {'key': 'sales',         'label': '月销量',   'path': '__INITIAL_STATE__.item.detail.monthlySales',           'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__INITIAL_STATE__.item.seller.shopName',              'fallback': None},
            {'key': 'comments',      'label': '评价数',   'path': '__INITIAL_STATE__.item.detail.commentCount',           'fallback': None},
        ],
    },

    # ========== 京东 ==========
    'jd': {
        'name': '京东',
        'icon': '🛍️',
        'color': '#E4393C',
        'homepage': 'https://www.jd.com',
        'login_url': 'https://www.jd.com/login',
        'note': '提取京东商品详情页数据',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '京东价',     'auto': True},
            {'key': 'original_price','label': '原价',      'auto': True},
            {'key': 'sales',        'label': '累计评价',   'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
            {'key': 'rating',       'label': '好评率',     'auto': True},
            {'key': 'images',       'label': '商品图',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.product.name',              'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '京东价',   'path': '__INITIAL_STATE__.product.priceSale',         'fallback': None},
            {'key': 'original_price','label': '原价',     'path': '__INITIAL_STATE__.product.priceMarket',       'fallback': None},
            {'key': 'sales',         'label': '累计评价', 'path': '__INITIAL_STATE__.product.commentCount',       'fallback': None},
            {'key': 'shop_name',     'label': '店铺名',   'path': '__INITIAL_STATE__.product.shop.name',         'fallback': None},
            {'key': 'rating',        'label': '好评率',   'path': '__INITIAL_STATE__.product.goodCommentRate',   'fallback': None},
            {'key': 'images',        'label': '商品图',   'path': '__INITIAL_STATE__.product.imageList',          'fallback': "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"},
        ],
        'api_patterns': ['/api/product/detail', '/sku/detail'],
    },

    # ========== 拼多多 ==========
    'pdd': {
        'name': '拼多多',
        'icon': '🎁',
        'color': '#E02E24',
        'homepage': 'https://www.pinduoduo.com',
        'login_url': '',
        'note': '拼多多为移动端优先，数据以页面meta和DOM提取为主',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '拼团价',     'auto': True},
            {'key': 'original_price','label': '单独购买价','auto': True},
            {'key': 'sales',        'label': '已拼件数',   'auto': True},
            {'key': 'shop_name',    'label': '店铺名',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '', 'fallback': "document.querySelector('title')?.textContent?.replace(/-\\s*拼多多/,'')?.trim()"},
            {'key': 'price',         'label': '拼团价',   'path': '', 'fallback': "document.querySelector('meta[property=\"product:price:amount\"]')?.getAttribute('content')"},
            {'key': 'original_price','label': '单独购买价','path': '', 'fallback': None},
            {'key': 'sales',         'label': '已拼件数', 'path': '', 'fallback': "document.querySelector('[class*=sale],[class*=sold]')?.textContent?.trim()"},
            {'key': 'shop_name',     'label': '店铺名',   'path': '', 'fallback': None},
        ],
    },

    # ========== 1688 ==========
    'ali1688': {
        'name': '1688',
        'icon': '🏭',
        'color': '#FF6A00',
        'homepage': 'https://www.1688.com',
        'login_url': 'https://www.1688.com/login',
        'note': '提取1688商品详情页数据（需登录查看价格）',
        'fields': [
            {'key': 'title',        'label': '商品标题',   'auto': True},
            {'key': 'price',        'label': '价格',       'auto': True},
            {'key': 'original_price','label': '建议零售价','auto': True},
            {'key': 'sales',        'label': '成交',       'auto': True},
            {'key': 'shop_name',    'label': '公司名',     'auto': True},
            {'key': 'images',       'label': '商品图',     'auto': True},
        ],
        'data_extract': [
            {'key': 'title',         'label': '商品标题', 'path': '__INITIAL_STATE__.detail.item.subject',        'fallback': "document.querySelector('title')?.textContent?.trim()"},
            {'key': 'price',         'label': '价格',     'path': '__INITIAL_STATE__.detail.item.price',          'fallback': None},
            {'key': 'original_price','label': '建议零售价','path': '__INITIAL_STATE__.detail.item.standardPrice', 'fallback': None},
            {'key': 'sales',         'label': '成交',     'path': '__INITIAL_STATE__.detail.item.saledCount',     'fallback': None},
            {'key': 'shop_name',     'label': '公司名',   'path': '__INITIAL_STATE__.detail.company.name',        'fallback': None},
            {'key': 'images',        'label': '商品图',   'path': '__INITIAL_STATE__.detail.item.imageList',       'fallback': "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"},
        ],
    },
}


# ==============================
# 关键词搜索配置
# ==============================
# 每个电商平台配 search_url 模板 + 搜索结果提取 JS
# {keyword} 会被替换为用户输入的搜索词
# {page} 会被替换为页码（从1开始）

SEARCH_CONFIGS = {
    'taobao': {
        'name': '淘宝',
        'search_url': 'https://s.taobao.com/search?q={keyword}&s={page_start}',
        'page_start_calc': lambda page: (page - 1) * 44,
        'item_selector': '.items .item, [class*="Item"]',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('.items .item, div[data-index], [class*="item"][data-id]');
            return JSON.stringify(Array.from(items).slice(0, 44).map(el => ({
                title: el.querySelector('.title a, [class*="title"] a')?.textContent?.trim() || '',
                price: el.querySelector('.price strong, .price g_price, [class*="price"]')?.textContent?.trim() || '',
                sales: el.querySelector('.deal-cnt, [class*="sale"]')?.textContent?.trim() || '',
                shop: el.querySelector('.shop a, [class*="shop"] a')?.textContent?.trim() || '',
                link: el.querySelector('.title a, [class*="pic"] a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
        'has_next_page': "!!document.querySelector('.next, a[title=\"下一页\"]')",
        'next_page_click': "document.querySelector('.next, a[title=\"下一页\"]')?.click()",
    },
    'tmall': {
        'name': '天猫',
        'search_url': 'https://list.tmall.com/search_product.htm?q={keyword}&s={page_start}',
        'page_start_calc': lambda page: (page - 1) * 60,
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('.product, [class*="product"], [data-id]');
            return JSON.stringify(Array.from(items).slice(0, 60).map(el => ({
                title: el.querySelector('.productTitle, [class*="title"]')?.textContent?.trim() || '',
                price: el.querySelector('.productPrice, [class*="price"]')?.textContent?.trim() || '',
                sales: el.querySelector('.productStatus, [class*="sale"]')?.textContent?.trim() || '',
                shop: el.querySelector('.shopName, [class*="shop"]')?.textContent?.trim() || '',
                link: el.querySelector('a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
    },
    'jd': {
        'name': '京东',
        'search_url': 'https://search.jd.com/Search?keyword={keyword}&page={page}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('.gl-item');
            return JSON.stringify(Array.from(items).slice(0, 60).map(el => ({
                title: el.querySelector('.p-name em, .p-name a')?.textContent?.trim() || '',
                price: el.querySelector('.p-price i, .p-price')?.textContent?.trim() || '',
                sales: el.querySelector('.p-commit strong, .p-commit')?.textContent?.trim() || '',
                shop: el.querySelector('.p-shop a, .J_shop_lnk')?.textContent?.trim() || '',
                link: el.querySelector('.p-name a')?.href || '',
                image: el.querySelector('.p-img img')?.src || '',
            })));
        }
        ''',
        'has_next_page': "!!document.querySelector('.pn-next, a[class*=\"next\"]')",
        'next_page_click': "document.querySelector('.pn-next, a[class*=\"next\"]')?.click()",
    },
    'pdd': {
        'name': '拼多多',
        'search_url': 'https://search.pinduoduo.com/goods?keyword={keyword}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('[class*="goods"]');
            return JSON.stringify(Array.from(items).slice(0, 50).map(el => ({
                title: el.querySelector('[class*="title"], [class*="name"]')?.textContent?.trim() || '',
                price: el.querySelector('[class*="price"], [class*="cost"]')?.textContent?.trim() || '',
                sales: el.querySelector('[class*="sale"], [class*="count"]')?.textContent?.trim() || '',
                shop: '',
                link: el.querySelector('a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
    },
    'ali1688': {
        'name': '1688',
        'search_url': 'https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}&beginPage={page}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('.offer-list-row .items, .sm-offer-item');
            return JSON.stringify(Array.from(items).slice(0, 50).map(el => ({
                title: el.querySelector('.title, [class*="title"] a')?.textContent?.trim() || '',
                price: el.querySelector('.price, [class*="price"]')?.textContent?.trim() || '',
                sales: el.querySelector('.deal, [class*="sale"], [class*="deal"]')?.textContent?.trim() || '',
                shop: el.querySelector('.company, [class*="company"] a')?.textContent?.trim() || '',
                link: el.querySelector('.title a, a[class*="title"]')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
        'has_next_page': "!!document.querySelector('.page-next, .next, a:contains(\"下一页\")')",
    },
    'douyin_mall': {
        'name': '抖音商城',
        'search_url': 'https://www.douyin.com/search/product?keyword={keyword}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('[class*="product"], [class*="goods"]');
            return JSON.stringify(Array.from(items).slice(0, 30).map(el => ({
                title: el.querySelector('[class*="title"], [class*="name"]')?.textContent?.trim() || '',
                price: el.querySelector('[class*="price"]')?.textContent?.trim() || '',
                sales: el.querySelector('[class*="sale"]')?.textContent?.trim() || '',
                shop: el.querySelector('[class*="shop"], [class*="store"]')?.textContent?.trim() || '',
                link: el.querySelector('a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
    },
    'kuaishou_mall': {
        'name': '快手商城',
        'search_url': 'https://www.kuaishou.com/search/product?keyword={keyword}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('[class*="product"], [class*="goods"]');
            return JSON.stringify(Array.from(items).slice(0, 30).map(el => ({
                title: el.querySelector('[class*="title"]')?.textContent?.trim() || '',
                price: el.querySelector('[class*="price"]')?.textContent?.trim() || '',
                sales: el.querySelector('[class*="sale"]')?.textContent?.trim() || '',
                shop: el.querySelector('[class*="shop"]')?.textContent?.trim() || '',
                link: el.querySelector('a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
    },
    'xhs_mall': {
        'name': '小红书商城',
        'search_url': 'https://www.xiaohongshu.com/search/product?keyword={keyword}',
        'extract_js': '''
        () => {
            const items = document.querySelectorAll('[class*="product"], [class*="goods"]');
            return JSON.stringify(Array.from(items).slice(0, 30).map(el => ({
                title: el.querySelector('[class*="title"]')?.textContent?.trim() || '',
                price: el.querySelector('[class*="price"]')?.textContent?.trim() || '',
                sales: '',
                shop: el.querySelector('[class*="shop"]')?.textContent?.trim() || '',
                link: el.querySelector('a')?.href || '',
                image: el.querySelector('img')?.src || '',
            })));
        }
        ''',
    },
}


# 用于 app.py 后向兼容：保留带长 js_extract 字符串的格式
# 新的统一提取器通过 make_extractor_js() 动态生成
def get_js_extract(platform_key: str) -> str:
    """根据平台配置生成统一提取脚本"""
    preset = PLATFORM_PRESETS.get(platform_key)
    if not preset or not preset.get('data_extract'):
        return ''
    return make_extractor_js(preset['data_extract'])


# ==============================
# douyin_crawler 平台配置 (商品采集)
# ==============================
PLATFORM_EMULATOR_CONFIGS = {
    'douyin': {
        'name': '抖音',
        'icon': '🎵',
        'package_name': 'com.ss.android.ugc.aweme',
        'mitm_domains': ['douyin.com', 'snssdk.com', 'amemv.com', 'byte'],
        'api_paths': ['search', 'product', 'goods', 'ecom', 'commodity'],
        'search_entry_texts': ['搜索'],
        'product_tab_texts': ['商品'],
        'swipe_wait': 2.2,
        'wait_after_search': 4.0,
        'ui_extract_fn': 'extract_douyin_products',
    },
    'kuaishou': {
        'name': '快手',
        'icon': '📷',
        'package_name': 'com.kuaishou.nebula',
        'mitm_domains': ['kuaishou.com', 'kwai.com'],
        'api_paths': ['search', 'product', 'goods'],
        'search_entry_texts': ['搜索'],
        'product_tab_texts': ['商品'],
        'swipe_wait': 2.0,
        'wait_after_search': 4.0,
        'ui_extract_fn': 'extract_kuaishou_products',
    },
    'xhs': {
        'name': '小红书',
        'icon': '📕',
        'package_name': 'com.xingin.xhs',
        'mitm_domains': ['xiaohongshu.com', 'xingin.com'],
        'api_paths': ['search', 'product', 'goods', 'commodity'],
        'search_entry_texts': ['搜索'],
        'product_tab_texts': ['商品', '商城'],
        'swipe_wait': 2.5,
        'wait_after_search': 5.0,
        'ui_extract_fn': 'extract_xhs_products',
    },
}


def get_emulator_platform(platform_key: str) -> dict | None:
    """获取 douyin_crawler 平台配置"""
    return PLATFORM_EMULATOR_CONFIGS.get(platform_key)
