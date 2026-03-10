import re
import base64
import urllib.parse
from typing import List, Dict
from dataclasses import dataclass

import cloudscraper
from bs4 import BeautifulSoup
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core import AstrBotConfig
import astrbot.api.message_components as Comp

# ========== 1. 配置映射类（从配置文件读取参数） ==========
@dataclass
class MagnetConfig:
    """磁力搜索配置类"""
    base_url: str          # 站点基础地址
    search_path: str       # 搜索接口路径
    max_results: int       # 最大返回结果数
    request_timeout: int   # 请求超时时间（秒）
    captcha_cookies: Dict[str, str] = None  # 验证Cookie（固定值）

    def __post_init__(self):
        # 初始化固定验证Cookie
        self.captcha_cookies = {
            "sssfwz": "qwsdsddsdsdse", 
            "sssfwz2": "qwsdsddsdsdse",
            "aywcUid": "lwgkvwDiYQ_20211009155217"
        }
        # 处理base_url结尾的/（统一格式：不带结尾/）
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        # 处理search_path开头的/（统一格式：带开头/）
        if not self.search_path.startswith("/"):
            self.search_path = f"/{self.search_path}"

# ========== 2. 核心工具类 ==========
class MagnetUtils:
    @staticmethod
    def decrypt_base64(encrypted_str: str) -> str:
        """Base64解密"""
        try:
            encrypted_str = encrypted_str.ljust(len(encrypted_str) + (4 - len(encrypted_str) % 4) % 4, '=')
            decoded = base64.b64decode(encrypted_str).decode('utf-8', errors='ignore')
            return urllib.parse.unquote(decoded)
        except Exception as e:
            logger.warning(f"Base64解密失败：{str(e)}")
            return ""

    @staticmethod
    def get_full_url(base_url: str, relative_url: str) -> str:
        """拼接完整URL"""
        if relative_url.startswith("http"):
            return relative_url
        if relative_url.startswith("./"):
            return f"{base_url}/{relative_url[2:]}"
        if relative_url.startswith("/"):
            return f"{base_url}{relative_url}"
        return f"{base_url}/{relative_url}"
    
    @staticmethod
    def get_sort_param(sort_keyword: str) -> str:
        """
        排序关键词
        """
        sort_mapping = {
            "相关度": "",
            "大小": "length",
            "文件大小": "length",
            "热门": "hot",
            "热门程度": "hot",
            "时间": "time",
            "最新": "time",
        }
        # 提高鲁棒性
        sort_keyword = sort_keyword.strip().lower()
        for key, value in sort_mapping.items():
            if key.lower() == sort_keyword:
                return value
        # 匹配不到返回空
        return ""

# ========== 3. 核心搜索服务 ==========
class MagnetSearchService:
    def __init__(self, config: MagnetConfig):
        self.config = config
        self.scraper = cloudscraper.create_scraper()
        # 设置默认headers
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.70 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": self.config.base_url,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.config.base_url
        })
        
        # 设置验证cookie
        for cookie_name, cookie_value in self.config.captcha_cookies.items():
            self.scraper.cookies.set(cookie_name, cookie_value)

    def _detect_challenge_page(self, content: str) -> bool:
        """检测是否为验证页面"""
        challenge_indicators = [
            'Checking your browser before accessing',
            'You are being redirected',
            'Checking if the site connection is secure',
            'enable javascript',
            'cloudflare',
            'ray id',
            '执行安全验证',  # 中文验证页面
            '确认您是真人',
            'cf-box',      # 验证框元素
            'challenge-success',  # 验证成功元素
            'click to verify'     # 点击验证
        ]
        content_lower = content.lower()
        return any(indicator.lower() in content_lower for indicator in challenge_indicators)

    async def search(self, keyword: str, sort_param: str = "") -> List[str]:
        """搜索逻辑：使用配置文件的站点/接口/结果数"""
        results = []

        try:
            # ========== 先访问首页设置cookie ==========
            logger.info("访问首页以设置验证cookie...")
            home_response = self.scraper.get(self.config.base_url, timeout=self.config.request_timeout)
            
            # 检查首页是否需要验证
            if self._detect_challenge_page(home_response.text):
                logger.warning("首页检测到验证页面")
                return ["网站需要人工验证，请先在浏览器中访问完成验证后再使用本功能"]

            # ========== 构造搜索URL ==========
            search_url = f"{self.config.base_url}{self.config.search_path}?name={urllib.parse.quote(keyword)}"
            # 拼接排序参数
            if sort_param:
                search_url += f"&sort={sort_param}"
            logger.debug(f"GET请求：{search_url}")
            
            # 使用cloudscraper发起请求
            response = self.scraper.get(search_url, timeout=self.config.request_timeout)
            logger.debug(f"响应状态码：{response.status_code}")
            
            # 检查是否遇到验证页面
            if self._detect_challenge_page(response.text):
                logger.warning("搜索页面检测到验证页面")
                return ["网站需要人工验证，请先在浏览器中访问完成验证后再使用本功能"]
            
            # 提取原始响应
            raw_html = response.text

            # ========== 解密原始响应 ==========
            encrypt_match = re.search(r"window\.atob\('([^']+)'", raw_html)
            if not encrypt_match:
                logger.warning(f"未找到window.atob加密串")
                # 尝试查找其他可能的加密方式
                encrypt_matches = re.findall(r'"([^"]*(?:atob|btoa)[^"]*)"', raw_html)
                if encrypt_matches:
                    # 尝试处理可能的加密内容
                    for match in encrypt_matches:
                        if len(match) > 50:  # 假设加密字符串长度大于50
                            try:
                                decrypted_content = MagnetUtils.decrypt_base64(match)
                                if decrypted_content and len(decrypted_content) > len(raw_html):
                                    raw_html = decrypted_content
                                    break
                            except:
                                continue
                
                if not encrypt_match and 'atob' not in raw_html:
                    logger.warning(f"页面内容：{raw_html[:500]}...")
                    return []
            
            decrypted_html = MagnetUtils.decrypt_base64(encrypt_match.group(1))

            # ========== 提取xq.php链接（使用配置） ==========
            soup = BeautifulSoup(decrypted_html, "lxml")
            result_container = soup.find("ul", id="Search_list_wrapper")
            if not result_container:
                logger.warning(f"解密后仍无搜索结果容器")
                # 尝试其他可能的选择器
                result_containers = soup.find_all(["div", "ul", "ol"], class_=re.compile(r".*search.*|.*result.*|.*list.*", re.I))
                for container in result_containers:
                    if len(container.find_all("li")) > 0:
                        result_container = container
                        break
                
                if not result_container:
                    logger.warning("未能找到结果容器")
                    return []

            detail_links = []
            processed_urls = set()
            # 遍历结果：最多取配置的max_results条
            for idx, li in enumerate(result_container.find_all("li")):
                if idx >= self.config.max_results:  # 从配置读取最大结果数
                    break
                if li.find("ul", class_="pagination"):
                    continue

                link_tag = li.find("a", href=re.compile(r"xq\.php\?key="))
                if not link_tag:
                    # 尝试其他可能的链接模式
                    link_tag = li.find("a", href=re.compile(r"\.php\?"))
                
                if not link_tag:
                    continue

                full_url = MagnetUtils.get_full_url(self.config.base_url, link_tag.get("href"))
                if full_url in processed_urls:
                    continue
                processed_urls.add(full_url)

                # 提取基础信息
                title = link_tag.text.strip() or f"搜索结果{idx+1}"
                size = re.search(r"文件大小：([0-9.]+ [GMK]B)", li.text)
                size = size.group(1).strip() if size else "未知大小"
                create_time = re.search(r"创建时间：(\d{4}-\d{2}-\d{2})", li.text)
                create_time = create_time.group(1).strip() if create_time else "未知时间"

                detail_links.append({
                    "url": full_url,
                    "title": title,
                    "size": size,
                    "create_time": create_time
                })

            if not detail_links:
                return []

            # ========== 解析详情页 ==========
            for link in detail_links:
                try:
                    detail_resp = self.scraper.get(link["url"], timeout=self.config.request_timeout)
                    
                    # 检查详情页是否也需要验证
                    if self._detect_challenge_page(detail_resp.text):
                        logger.warning(f"详情页遇到验证：{link['title']}")
                        results.append(f"标题：{link['title']}\n解析失败：遇到人机验证\n文件大小：{link['size']}")
                        continue

                    detail_raw = detail_resp.text

                    # 解密详情页
                    detail_encrypt = re.search(r"window\.atob\('([^']+)'", detail_raw)
                    detail_html = detail_raw
                    if detail_encrypt:
                        detail_html = MagnetUtils.decrypt_base64(detail_encrypt.group(1))

                    # 提取磁力链接
                    magnet_link = None
                    soup_detail = BeautifulSoup(detail_html, "lxml")
                    magnet_a = soup_detail.find("a", href=re.compile(r"magnet:\?xt=urn:btih:"))
                    if magnet_a:
                        magnet_link = magnet_a.get("href").strip()
                    if not magnet_link:
                        # 尝试在文本中查找
                        magnet_matches = re.findall(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+', detail_html)
                        if magnet_matches:
                            magnet_link = magnet_matches[0].strip()
                    
                    if not magnet_link:
                        # 尝试查找可能的JavaScript变量
                        js_matches = re.findall(r'"(magnet:\?xt=[^"]*)"', detail_html)
                        for match in js_matches:
                            if match.startswith("magnet:?xt=urn:btih:"):
                                magnet_link = match
                                break

                    # 构造结果
                    results.append(
                        f"标题：{link['title']}\n"
                        f"磁力链接：{magnet_link or '未提取到'}\n"
                        f"文件大小：{link['size']}\n"
                        f"收录时间：{link['create_time']}"
                    )
                except Exception as e:
                    results.append(f"标题：{link['title']}\n解析失败：{str(e)[:30]}\n文件大小：{link['size']}")

        except Exception as e:
            logger.error(f"搜索异常：{str(e)}")
            results = [f"搜索失败：{str(e)[:50]}"]

        return results

# ========== 4. 插件主类 ==========
@register(
    "astrbot_plugin_BitTorrent",
    "NightDust981989",
    "BitTorrent磁力搜索",
    "1.2.0",
    "https://github.com/NightDust981989/astrbot_plugin_BitTorrent"
)
class MagnetSearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config        
        # ========== 从插件配置文件读取参数 ==========
        magnet_config_dict = self.config.get("magnet_search", {})

        base_url = magnet_config_dict.get("base_url", "https://clg2.clgapp1.xyz")
        search_path = magnet_config_dict.get("search_path", "/cllj.php")
        max_results = int(magnet_config_dict.get("max_results", 3))
        request_timeout = int(magnet_config_dict.get("request_timeout", 15))

        # 初始化配置类
        self.magnet_config = MagnetConfig(
            base_url=base_url,
            search_path=search_path,
            max_results=max_results,
            request_timeout=request_timeout
        )
        self.search_service = MagnetSearchService(self.magnet_config)
        logger.info(f"磁力搜索插件初始化完成，使用站点：{base_url}{search_path}")

    @filter.command("bt")
    async def magnet_search_handler(self, event: AstrMessageEvent):
        """
        磁力链接搜索指令
        使用方式：bt （排序方式） [关键词]
        示例：bt 安达与岛村 / bt 热门 安达与岛村
        """
        message = event.message_str.strip()
        args = message.split()
    
        # 初始化消息链
        chain = []
    
        if len(args) < 2 or args[0] != "bt":
            # 提示整合到chain
            chain.append(Comp.Plain("用法：bt （排序方式） [关键词]\n示例：bt 热门 安达与岛村"))
            yield event.chain_result(chain)
            return
        
        # 解析排序参数和关键词
        sort_keyword = ""
        keyword = ""
        if len(args) == 2:
            # 默认相关度
            keyword = args[1]
        else:
            # 有排序参数
            sort_keyword = args[1]
            keyword = " ".join(args[2:])
    
        # 转换排序关键词为sort
        sort_param = MagnetUtils.get_sort_param(sort_keyword)
        # 执行搜索
        results = await self.search_service.search(keyword, sort_param)
    
        if not results:
            # 无结果的chain
            chain.append(Comp.Plain("未找到相关磁力链接，网站失效或网络问题"))
        else:
            # 有结果时拼接完整内容
            chain.append(Comp.Plain(f"共找到 {len(results)} 条有效结果："))
            for idx, res in enumerate(results, 1):
                chain.append(Comp.Plain(f"‎\n===== 结果 {idx} =====\n‎{res}"))
    
        # 返回完整的消息链
        yield event.chain_result(chain)