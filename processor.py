from bs4 import BeautifulSoup
import httpx
from termcolor import colored
from typing import List, Dict, Optional
import openai
from groq import Groq
import asyncio
from markdown import markdown
import re
import os
import json
import aiohttp
from groq import AsyncGroq

# Constants
CHUNK_SIZE = 16000  # Safe chunk size for 64k context window
MAX_OUTPUT_TOKENS = 7000  # Safe output size
HTTP_TIMEOUT = 30.0  # Timeout in seconds
MAX_RETRIES = 3
RETRY_DELAY = 1  # Delay between retries in seconds

SYSTEM_PROMPT = """You are a documentation processor. Your task is to:
1. Extract the main content from HTML documentation pages
2. Remove navigation elements, headers, footers, and other non-documentation content
3. Convert the content to clean markdown format
4. Ensure all internal links are updated to work within a single markdown file
5. Maintain the original formatting and structure of the documentation

Focus only on the actual documentation content and ignore any UI elements."""

class DocumentationProcessor:
    def __init__(self, api_key: str, use_groq: bool = False):
        self.api_key = api_key
        self.use_groq = use_groq
        self.session = None
        self.groq_client = None
        
        if use_groq:
            self.groq_client = AsyncGroq(api_key=api_key)
        
    async def _init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
            
    async def close(self):
        if self.session:
            await self.session.close()
            
    async def _process_with_deepseek(self, content: str, system_prompt: str) -> str:
        await self._init_session()
        
        try:
            async with self.session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content}
                    ]
                }
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(colored(f"DeepSeek API error: {error_text}", "red"))
                    raise Exception(f"Failed to process with DeepSeek API: {error_text}")
                    
                result = await response.json()
                return result["choices"][0]["message"]["content"]
                
        except Exception as e:
            print(colored(f"Error processing with DeepSeek: {str(e)}", "red"))
            raise
            
    async def _process_with_groq(self, content: str, system_prompt: str) -> str:
        try:
            chat_completion = await self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                model="mixtral-8x7b-32768",
                temperature=0.5,
                max_tokens=32768
            )
            return chat_completion.choices[0].message.content
            
        except Exception as e:
            print(colored(f"Error processing with Groq: {str(e)}", "red"))
            raise
            
    async def _process_content(self, content: str, system_prompt: str) -> str:
        if self.use_groq:
            return await self._process_with_groq(content, system_prompt)
        else:
            return await self._process_with_deepseek(content, system_prompt)
            
    def _generate_toc(self, pages: Dict) -> str:
        toc = []
        
        def process_page(page: Dict, level: int = 0):
            if not page.get("selected", True):  # Skip unselected pages
                return
                
            indent = "  " * level
            title = page.get("title", "").strip()
            url = page.get("url", "").strip()
            
            if title and url:
                toc.append(f"{indent}- {title}")
                
            for child in page.get("children", []):
                process_page(child, level + 1)
                
        process_page(pages)
        return "\n".join(toc)
        
    def _get_selected_pages(self, pages: Dict) -> List[Dict]:
        selected = []
        
        def collect_pages(page: Dict):
            if page.get("selected", True):
                title = page.get("title", "").strip()
                url = page.get("url", "").strip()
                if title and url:
                    selected.append({
                        "title": title,
                        "url": url
                    })
            
            for child in page.get("children", []):
                collect_pages(child)
                
        collect_pages(pages)
        return selected
        
    async def _process_single_page(self, page: Dict) -> str:
        """Process a single page and return its markdown content."""
        try:
            print(colored(f"Processing page: {page['title']}", "blue"))
            
            system_prompt = """You are a technical documentation expert. Your task is to convert the provided documentation page into clean, well-formatted markdown. Please:
1. Preserve all technical information accurately
2. Ensure code examples and technical terms are properly formatted
3. Use clear and consistent markdown formatting
4. Maintain the original structure and hierarchy
5. Remove any navigation elements or non-documentation content"""

            content = f"""Please convert this documentation page into markdown format:

Title: {page['title']}
URL: {page['url']}

Please focus only on the content and ensure it's well-formatted markdown."""

            markdown_content = await self._process_content(content, system_prompt)
            
            # Format the page with our delimiter template
            formatted_content = f"""Page: {page['title']}
URL: {page['url']}
^^ Begin Content ^^

{markdown_content.strip()}

---"""
            
            return formatted_content
            
        except Exception as e:
            print(colored(f"Error processing page {page['title']}: {str(e)}", "red"))
            raise
            
    async def process_pages(self, pages: Dict) -> str:
        try:
            print(colored("Collecting selected pages...", "blue"))
            selected_pages = self._get_selected_pages(pages)
            
            if not selected_pages:
                raise Exception("No pages selected for processing")
                
            print(colored(f"Found {len(selected_pages)} selected pages", "blue"))
            
            print(colored("Generating table of contents...", "blue"))
            toc = self._generate_toc(pages)
            
            print(colored("Processing pages individually...", "blue"))
            processed_pages = []
            
            # Process each page individually
            for page in selected_pages:
                try:
                    content = await self._process_single_page(page)
                    processed_pages.append(content)
                except Exception as e:
                    print(colored(f"Failed to process page {page['title']}: {str(e)}", "red"))
                    # Continue with other pages even if one fails
                    continue
            
            if not processed_pages:
                raise Exception("No pages were successfully processed")
            
            # Combine everything into the final markdown document
            final_markdown = f"""# Documentation

{toc}

---

{chr(10).join(processed_pages)}"""
            
            print(colored("Successfully generated complete markdown document!", "green"))
            return final_markdown
            
        except Exception as e:
            print(colored(f"Error processing pages: {str(e)}", "red"))
            raise Exception(f"Failed to generate markdown: {str(e)}") 