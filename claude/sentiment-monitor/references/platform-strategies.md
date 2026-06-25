# 平台检索策略参考

> 本文档是 `sentiment-monitor` SKILL.md 的补充，详细记录五大平台的检索策略。
> 执行采集前，**必须先读取 web-access 对应站点的经验文件**，本文档提供舆情场景下的补充策略。

## 前置：读取站点经验

在访问任何平台前，先读取 web-access skill 的对应站点经验：

| 平台 | 站点经验文件 |
|------|-------------|
| 抖音 | `skills/web-access/references/site-patterns/douyin.com.md` |
| B站 | `skills/web-access/references/site-patterns/bilibili.com.md` |
| 小红书 | `skills/web-access/references/site-patterns/xiaohongshu.com.md` |
| 贴吧 | `skills/web-access/references/site-patterns/tieba.baidu.com.md` | ✅ |
| 微博 | `skills/web-access/references/site-patterns/weibo.com.md` | ✅ |

---

## 一、抖音 — CDP 优先

### 最佳路径

```
1. 构造搜索 URL → 2. 滚动加载 → 3. 提取视频 ID 列表 → 4. 进入详情页提取评论
```

### 搜索页提取（快速扫描适用）

```js
// 获取视频卡片列表（含标题、作者、点赞数）
(() => {
  const cards = document.querySelectorAll('[id^="waterfall_item_"]');
  return Array.from(cards).slice(0, 20).map(card => {
    const vid = card.id.replace('waterfall_item_', '');
    const text = card.innerText;
    // 解析格式：标题 \n 作者 · 时间 \n 点赞数
    const lines = text.split('\n').filter(l => l.trim());
    return { vid, title: lines[0] || '', author: lines[1] || '', likes: lines[2] || '' };
  });
})()
```

### 详情页提取（专题/周期报告适用）

```js
// 在 https://www.douyin.com/video/{video_id} 页面
(() => {
  const text = document.body.innerText;
  // 找 "全部评论" 后的内容块
  const idx = text.indexOf('全部评论');
  const comments = idx > -1 ? text.substring(idx, idx + 3000) : text.substring(0, 3000);
  return {
    stats: text.match(/(\d+\.?\d*万?)\s*点赞.*?(\d+\.?\d*万?)\s*评论/),
    content: comments
  };
})()
```

### 关键注意事项
- 搜索页模态层不加载评论，必须进入 `/video/{id}` 路径
- `innerText` 可能截断长页面，需要分区域提取
- 滚动到底部触发懒加载后再提取
- 如登录态丢失（页面空白/重定向），告知用户在 Chrome 中登录抖音

### 快扫建议
- 快速扫描时可只提取搜索页的标题和点赞数，不进详情页
- 标题和点赞数已经足够判断舆论风向

---

## 二、B站 — CDP + API 组合

### 最佳路径

```
1. 搜索页提取视频 → 2. 浏览器内 fetch 评论 API → 3. 对比弹幕/评论热点
```

### 搜索页提取

```js
// 搜索页提取视频列表
(() => {
  return Array.from(document.querySelectorAll('.video-list-item, .search-video-item, [class*="video"]'))
    .slice(0, 20)
    .map(el => ({
      title: el.querySelector('[class*="title"], h3, a[href*="video"]')?.textContent?.trim() || '',
      link: el.querySelector('a[href*="video/BV"]')?.href || '',
      views: el.querySelector('[class*="play"], [class*="view"]')?.textContent?.trim() || '',
      duration: el.querySelector('[class*="duration"], [class*="length"]')?.textContent?.trim() || ''
    }))
    .filter(v => v.title);
})()
```

### 获取视频详情+评论

```js
// 在视频详情页中执行，通过 __INITIAL_STATE__ 获取数据
(() => {
  try {
    const state = window.__INITIAL_STATE__;
    const vd = state.videoData;
    return JSON.stringify({
      aid: vd.aid, bvid: vd.bvid,
      title: vd.title, desc: vd.desc?.substring(0, 500),
      stats: vd.stat,
      tags: vd.tag || []
    });
  } catch(e) { return 'Error: ' + e.message; }
})()
```

### 获取评论（老接口，无需 wbi 签名）

在浏览器内 fetch（自带 cookie/Referer）：
```js
// sort=2 按热度排序
fetch('/x/v2/reply?type=1&oid={aid}&pn=1&ps=20&sort=2')
  .then(r => r.json())
  .then(d => d.data.replies.map(r => ({
    user: r.member.uname,
    content: r.content.message,
    likes: r.like,
    ctime: r.ctime
  })))
```

### 关键注意事项
- bash curl 请求 API 通常空返回，必须用浏览器内 fetch
- 新 wbi 接口经常 403，**只用老接口 `/x/v2/reply`**
- `__INITIAL_STATE__` 需用 try/catch 包裹
- 视频时长单位秒

### 快扫建议
- 提取搜索页标题+播放量即可获取话题热度
- 高播放量视频的标题本身就是舆情风向标

---

## 三、小红书 — 必须 CDP

### 核心认知

> **小红书是五大平台中对自动化最不友好的**。强反爬机制意味着 WebSearch/WebFetch 基本无效，必须走 CDP 浏览器。

### 搜索页提取

```
URL 模式：https://www.xiaohongshu.com/search_result?keyword={URL_ENCODED}&type=51
type=51 为综合排序
```

```js
// 最佳方式：innerText 文本解析
// 格式：标题 \n 作者 \n 时间 · 点赞数
(() => {
  const text = document.body.innerText;
  const lines = text.split('\n').filter(l => l.trim());
  // 找到搜索结果区域的文本，过滤掉导航和推荐
  return lines.slice(lines.findIndex(l => l.includes('综合') || l.includes('最热')), 200)
    .join('\n');
})()
```

### 笔记详情页

- 从搜索页提取 explore ID（24位 hex），构造 `https://www.xiaohongshu.com/explore/{id}` 在新 tab 打开
- 详情页包含正文和评论
- 可能触发登录要求

### 关键注意事项
- CSS 类名是 Vue SFC scoped 生成的，不稳定，**不要依赖 CSS 选择器**
- 大量 `display:none` 的幽灵链接充斥 DOM，需要去重
- 每次滚动间隔 2 秒以上，避免触发风控
- 短时间内大量打开 tab 会触发验证码

### 快扫建议
- 直接提取搜索页 innerText 即可，不进详情页
- 小红书内容天然偏向消费/审美/情感维度，是获取女性玩家视角的关键渠道

---

## 四、贴吧 — WebSearch + CDP 兜底

### 特点

- 贴吧内容结构简单，百度搜索索引较好
- WebSearch 通常能拿到贴吧帖子的标题和片段
- 需要深度分析时，用 CDP 直接访问帖子页获取完整讨论

### WebSearch 策略（优先）

搜索词模板：
```
"永劫无间" 周年庆 site:tieba.baidu.com
或
{游戏名} {话题} 贴吧 讨论
```

### CDP 深度抓取

```js
// 帖子页提取主楼+回复
(() => {
  const floor = document.querySelectorAll('.l_post, [class*="post"], .d_post_content');
  return Array.from(floor).slice(0, 30).map(el => ({
    user: el.querySelector('.d_name, [class*="user"]')?.textContent?.trim() || '',
    content: el.querySelector('.d_post_content, [class*="content"]')?.textContent?.trim()?.substring(0, 300) || '',
    time: el.querySelector('[class*="time"], [class*="date"]')?.textContent?.trim() || ''
  })).filter(f => f.content);
})()
```

### 快扫建议
- 贴吧是负面情绪富矿——快扫时重点关注首页帖子标题的情感倾向
- 贴吧帖子标题通常直接表达态度（"xx真垃圾""xx太香了"），扫标题即可判断基调

---

## 五、微博 — WebSearch + CDP 搜索页

### 特点

- 微博搜索结果受反爬限制，WebSearch 覆盖率不稳定
- CDP 访问 `https://s.weibo.com/weibo?q={关键词}` 通常有效
- 微博的舆情价值在于：破圈事件的扩散速度和转发链

### WebSearch 策略

搜索词模板：
```
{游戏名} {事件} 微博 热搜
或
{游戏名} {话题} site:weibo.com
```

### CDP 搜索页

```js
// 微博搜索页提取
(() => {
  const text = document.body.innerText;
  // 微博搜索结果通常按时间或热度排列
  const start = text.indexOf('实时') > -1 ? text.indexOf('实时') : text.indexOf('综合');
  return text.substring(start || 0, (start || 0) + 3000);
})()
```

### 快扫建议
- 微博不是永劫/D90 这类硬核竞技游戏的主舆论场
- 快扫时若 WebSearch 返回空，可标记为"声量低"而非反复重试

---

## 多平台并行策略

### 快扫模式（3平台，15-30分钟）

按话题选择最相关的 3 个平台：

| 话题类型 | 优先平台 |
|----------|---------|
| 版本更新/福利争议 | 贴吧 + B站 + 抖音 |
| 新英雄/新皮肤 | B站 + 抖音 + 小红书 |
| Bug/技术问题 | 贴吧 + B站 |
| 破圈事件/公关危机 | 微博 + 抖音 + B站 |
| 付费/商业化 | 贴吧 + 小红书 + B站 |

### 专题/周期模式（5平台，1-2小时）

全平台覆盖，顺序建议：
1. **先并行**：贴吧(WebSearch) + B站(WebSearch) + 抖音(CDP搜索页) — 快速获取概况
2. **再深入**：选择声量最高的2-3个平台做 CDP 深度抓取（进入详情页/评论区）
3. **最后扫尾**：微博+小红书(CDP) — 补充边缘视角

### WebSearch 与 CDP 分工

| 需求 | 工具 |
|------|------|
| 快速了解话题概况、发现热门帖子 | WebSearch（并行多平台，1分钟内出结果） |
| 获取评论详情、互动数据、验证内容真实性 | CDP（逐个平台深入） |
| 小红书任何内容 | CDP 必选，WebSearch 无效 |
| 抖音评论/互动详情 | CDP 必选 |
| 贴吧帖子概览 | WebSearch 通常足够 |
| B站视频元数据+评论 | CDP 浏览器内 fetch |
