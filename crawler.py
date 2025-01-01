import asyncio
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from termcolor import colored
import httpx
from typing import Set, List, Dict
import re

class DocumentationCrawler:
    def __init__(self):
        self.visited_urls: Set[str] = set()
        self.base_url: str = ""
        self.base_domain: str = ""
        # Add browser-like headers
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'DNT': '1',
        }
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            headers=self.headers,
            timeout=30.0
        )
    
    async def close(self):
        await self.client.aclose()
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and belongs to the same domain."""
        try:
            parsed = urlparse(url)
            base_parsed = urlparse(self.base_url)
            
            # Check if it's a valid URL and on the same domain
            is_valid = (
                bool(parsed.netloc) and
                bool(parsed.scheme) and
                parsed.netloc == self.base_domain and
                not any(ext in url.lower() for ext in ['.pdf', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.ttf'])
            )
            
            # Check if it's a documentation page or subpage
            is_doc_page = (
                parsed.path.startswith(base_parsed.path) or
                any(keyword in parsed.path.lower() for keyword in [
                    'documentation', 'docs', 'api', 'guide', 'reference', 'getting-started',
                    'authentication', 'web', 'youtube', 'crawl', 'map', 'scrape', 'transcript'
                ])
            )
            
            return is_valid and (is_doc_page or url == self.base_url)
            
        except Exception as e:
            print(colored(f"Error validating URL {url}: {str(e)}", "red"))
            return False
    
    def _clean_url(self, url: str) -> str:
        """Clean URL by removing fragments and query parameters."""
        try:
            parsed = urlparse(url)
            # Keep the trailing slash if it exists
            path = parsed.path if parsed.path.endswith('/') else parsed.path.rstrip('/')
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        except Exception as e:
            print(colored(f"Error cleaning URL {url}: {str(e)}", "red"))
            return url
    
    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """Fetch page content and return title and HTML."""
        try:
            print(colored(f"Fetching {url}", "cyan"))
            response = await self.client.get(url)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Get title from meta tags or title tag
            title = (
                soup.find('meta', property='og:title')
                or soup.find('meta', {'name': 'title'})
                or soup.title
            )
            title = title.get('content', '') if hasattr(title, 'get') else title.string if title else ''
            title = title.strip() or url.split('/')[-1]
            
            # If we're on the first page, try to extract documentation links from known patterns
            if url == self.base_url:
                # Add common documentation paths to check
                common_paths = [
                    '/documentation',
                    '/docs',
                    '/api',
                    '/guide',
                    '/reference',
                ]
                
                # Inject these paths into the HTML for discovery
                nav = soup.find('nav') or soup.new_tag('nav')
                for path in common_paths:
                    full_url = urljoin(self.base_url, path)
                    if self._is_valid_url(full_url):
                        link = soup.new_tag('a', href=path)
                        link.string = path
                        nav.append(link)
                
                # Also look for documentation links in the text
                doc_patterns = [
                    r'href="[^"]*documentation[^"]*"',
                    r'href="[^"]*docs[^"]*"',
                    r'href="[^"]*api[^"]*"',
                    r'href="/[^"]*"'  # Any internal link
                ]
                
                for pattern in doc_patterns:
                    for match in re.finditer(pattern, response.text):
                        href = re.search(r'href="([^"]*)"', match.group(0))
                        if href:
                            link = soup.new_tag('a', href=href.group(1))
                            nav.append(link)
            
            return title, str(soup)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # For 404 errors, just skip this page but don't stop crawling
                print(colored(f"Page not found: {url}", "yellow"))
                return None, None
            raise
        except Exception as e:
            print(colored(f"Error fetching {url}: {str(e)}", "red"))
            return None, None
    
    def _extract_links(self, html: str, current_url: str) -> List[str]:
        """Extract valid documentation links from HTML."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            links = set()  # Use a set to avoid duplicates
            
            # First try to find links in navigation elements
            nav_elements = soup.find_all(['nav', 'header', 'aside', 'div'], class_=lambda x: x and any(term in x.lower() for term in ['nav', 'menu', 'sidebar', 'toc']))
            
            # If no navigation elements found, look in the whole document
            elements_to_search = nav_elements if nav_elements else [soup]
            
            for element in elements_to_search:
                for a in element.find_all('a', href=True):
                    href = a['href']
                    
                    # Skip empty links and javascript links
                    if not href or href.startswith(('javascript:', '#', 'mailto:', 'tel:')):
                        continue
                    
                    # Handle relative URLs
                    if href.startswith('/'):
                        parsed_base = urlparse(self.base_url)
                        href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                    elif not href.startswith(('http://', 'https://')):
                        href = urljoin(current_url, href)
                    
                    clean_url = self._clean_url(href)
                    if clean_url not in self.visited_urls and self._is_valid_url(clean_url):
                        links.add(clean_url)
            
            # If we're on the first page, also look for documentation-specific links
            if current_url == self.base_url:
                doc_paths = [
                    '/documentation',
                    '/docs',
                    '/api',
                    '/guide',
                    '/reference',
                    '/documentation/getting-started',
                    '/documentation/authentication',
                    '/documentation/web',
                    '/documentation/youtube'
                ]
                
                for path in doc_paths:
                    full_url = urljoin(self.base_url, path)
                    clean_url = self._clean_url(full_url)
                    if clean_url not in self.visited_urls and self._is_valid_url(clean_url):
                        links.add(clean_url)
            
            # Sort links to maintain consistent order
            return sorted(list(links))
        except Exception as e:
            print(colored(f"Error extracting links from {current_url}: {str(e)}", "red"))
            return []
    
    def _organize_pages(self, pages: List[Dict]) -> Dict:
        """Organize pages into a hierarchical structure."""
        try:
            print(colored(f"\nOrganizing {len(pages)} pages:", "blue"))
            for page in pages:
                print(colored(f"  - {page['url']} -> {page['title']}", "blue"))
            
            # Find the starting page
            start_page = next((page for page in pages if page["url"] == self.base_url), pages[0])
            print(colored(f"\nRoot page: {start_page['url']} -> {start_page['title']}", "green"))
            
            # Create root node
            root = {
                "url": self.base_url,
                "title": start_page["title"],
                "children": []
            }

            # Group pages by their path depth for better organization
            url_groups = {}
            for page in pages:
                if page["url"] == self.base_url:
                    continue
                
                # Get path relative to base URL
                base_path = urlparse(self.base_url).path.rstrip('/')
                page_path = urlparse(page["url"]).path
                
                if base_path and page_path.startswith(base_path):
                    relative_path = page_path[len(base_path):].strip('/')
                else:
                    relative_path = page_path.strip('/')
                
                if not relative_path:
                    continue
                
                parts = relative_path.split('/')
                depth = len(parts)
                
                if depth not in url_groups:
                    url_groups[depth] = []
                url_groups[depth].append(page)
                print(colored(f"  Grouped {page['url']} at depth {depth}", "blue"))

            # Process pages level by level
            for depth in sorted(url_groups.keys()):
                for page in url_groups[depth]:
                    # Get path relative to base URL
                    base_path = urlparse(self.base_url).path.rstrip('/')
                    page_path = urlparse(page["url"]).path
                    
                    if base_path and page_path.startswith(base_path):
                        relative_path = page_path[len(base_path):].strip('/')
                    else:
                        relative_path = page_path.strip('/')
                    
                    parts = relative_path.split('/')
                    
                    # Find parent node
                    current = root
                    parent_path = self.base_url
                    
                    # Traverse the path to find/create parent nodes
                    for i in range(depth - 1):
                        parent_path = urljoin(parent_path, parts[i])
                        found = False
                        
                        for child in current["children"]:
                            if child["url"].rstrip('/') == parent_path.rstrip('/'):
                                current = child
                                found = True
                                break
                        
                        if not found:
                            # Create intermediate node if it doesn't exist
                            new_node = {
                                "url": parent_path,
                                "title": parts[i].replace("-", " ").title(),
                                "children": []
                            }
                            current["children"].append(new_node)
                            current = new_node
                            print(colored(f"  Created intermediate node: {new_node['url']} -> {new_node['title']}", "yellow"))
                    
                    # Add the page to its parent
                    page_node = {
                        "url": page["url"],
                        "title": page["title"],
                        "children": []
                    }
                    print(colored(f"  Adding page: {page_node['url']} -> {page_node['title']} to {current['url']}", "green"))
                    current["children"].append(page_node)

            # Sort children recursively
            def sort_children(node):
                if "children" in node:
                    node["children"].sort(key=lambda x: x.get("title", "").lower())
                    for child in node["children"]:
                        sort_children(child)
            
            sort_children(root)
            
            print(colored("\nFinal tree structure:", "green"))
            def print_tree(node, level=0):
                print(colored("  " * level + f"- {node['title']} ({node['url']})", "cyan"))
                for child in node.get("children", []):
                    print_tree(child, level + 1)
            
            print_tree(root)
            
            return root
            
        except Exception as e:
            print(colored(f"Error organizing pages: {str(e)}", "red"))
            # Return a simple structure if organization fails
            return {
                "url": self.base_url,
                "title": start_page["title"],
                "children": [
                    {"url": page["url"], "title": page["title"], "children": []}
                    for page in pages if page["url"] != self.base_url
                ]
            }

    async def crawl(self, start_url: str) -> Dict:
        """
        Crawl documentation starting from the given URL and return hierarchical structure.
        """
        if not start_url:
            print(colored("Error: No URL provided", "red"))
            return None

        try:
            print(colored(f"Starting crawl from {start_url}", "green"))
            self.base_url = start_url
            parsed_url = urlparse(start_url)
            if not parsed_url.scheme or not parsed_url.netloc:
                print(colored("Error: Invalid URL format", "red"))
                return None
                
            self.base_domain = parsed_url.netloc
            
            # First, verify we can access the starting URL
            try:
                response = await self.client.get(start_url)
                response.raise_for_status()
                initial_title, initial_html = await self._fetch_page(start_url)
                if not initial_html:
                    raise Exception("Could not fetch content from starting URL")
            except Exception as e:
                print(colored(f"Error: Failed to access starting URL: {str(e)}", "red"))
                return None
            
            # Collect all pages first
            all_pages = [{
                "url": start_url,
                "title": initial_title
            }]
            error_count = 0
            max_errors = 5  # Maximum number of consecutive errors before giving up
            
            async def _crawl_page(url: str) -> None:
                nonlocal error_count
                if url in self.visited_urls:
                    return
                
                try:
                    self.visited_urls.add(url)
                    title, html = await self._fetch_page(url)
                    
                    if title and html:  # Only add pages that were successfully fetched
                        all_pages.append({
                            "url": url,
                            "title": title,
                        })
                        error_count = 0  # Reset error count on success
                        
                        links = self._extract_links(html, url)
                        tasks = [_crawl_page(link) for link in links]
                        await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    error_count += 1
                    print(colored(f"Warning: Error processing {url}: {str(e)}", "yellow"))
                    if error_count >= max_errors:
                        print(colored("Too many consecutive errors, stopping crawl", "red"))
                        return
            
            # Start crawling from links found in the starting page
            initial_links = self._extract_links(initial_html, start_url)
            tasks = [_crawl_page(link) for link in initial_links]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            if len(all_pages) <= 1:  # Only the starting page was found
                print(colored("Error: No additional pages found", "red"))
                return None
            
            # Filter out unwanted pages
            filtered_pages = [
                page for page in all_pages
                if not any(skip in page["url"].lower() for skip in [
                    '/_next/', '/manifest.', '/cdn-cgi/', '.js', '.css', '.png', '.jpg',
                    '.jpeg', '.gif', '.ico', '.svg', '.woff', '.ttf'
                ])
            ]
            
            if not filtered_pages:
                print(colored("Error: No valid documentation pages found after filtering", "red"))
                return None
            
            # Organize pages into hierarchy
            result = self._organize_pages(filtered_pages)
            if not result:
                print(colored("Error: Failed to organize pages", "red"))
                return None
            
            print(colored(f"Crawl completed. Found {len(filtered_pages)} valid pages.", "green"))
            return result
            
        except Exception as e:
            print(colored(f"Error during crawl: {str(e)}", "red"))
            return None
        finally:
            await self.close() 