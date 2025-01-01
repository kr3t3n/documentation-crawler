import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from termcolor import colored
import httpx
from bs4 import BeautifulSoup
import openai
import asyncio
from typing import List, Dict, Optional
from pydantic import BaseModel

from crawler import DocumentationCrawler
from processor import DocumentationProcessor

# Constants
CHUNK_SIZE = 16000  # Safe chunk size for 64k context window (leaving room for system prompts)
MAX_OUTPUT_TOKENS = 7000  # Safe output size (below 8k limit)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Initialize FastAPI app
app = FastAPI(title="Documentation Compiler")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Pydantic models
class CrawlRequest(BaseModel):
    url: str
    api_key: str
    use_groq: bool = False

class GenerateRequest(BaseModel):
    pages: List[Dict]
    api_key: str
    use_groq: bool = False

class PageNode(BaseModel):
    url: str
    title: str
    children: List['PageNode'] = []
    selected: bool = True

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/crawl")
async def crawl_endpoint(request: CrawlRequest):
    crawler = None
    try:
        print(colored("Received crawl request", "green"))
        print(colored(f"Crawling URL: {request.url}", "blue"))
        crawler = DocumentationCrawler()
        result = await crawler.crawl(request.url)
        
        if result is None:
            print(colored("Failed to crawl documentation", "red"))
            raise HTTPException(
                status_code=400,
                detail="Failed to crawl documentation. The URL might be invalid or the site might be blocking access."
            )
            
        # Ensure we have at least some valid pages
        if not result.get("children"):
            print(colored("No documentation pages found", "red"))
            raise HTTPException(
                status_code=400,
                detail="No documentation pages found at the provided URL."
            )
            
        print(colored("Successfully crawled documentation", "green"))
        print(colored(f"Found {len(result.get('children', []))} pages", "blue"))
        return {"pages": result}
        
    except HTTPException:
        raise
    except Exception as e:
        print(colored(f"Error in crawl endpoint: {str(e)}", "red"))
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while crawling: {str(e)}"
        )
    finally:
        if crawler:
            await crawler.close()

@app.post("/api/generate")
async def generate_endpoint(request: GenerateRequest):
    processor = None
    try:
        print(colored("Received generate request", "green"))
        print(colored(f"Using {'Groq' if request.use_groq else 'DeepSeek'} API", "blue"))
        processor = DocumentationProcessor(request.api_key, use_groq=request.use_groq)
        
        # Take the first page as it contains the full tree
        root_page = request.pages[0] if request.pages else None
        if not root_page:
            print(colored("No pages provided in request", "red"))
            raise HTTPException(status_code=400, detail="No pages provided")
            
        markdown_content = await processor.process_pages(root_page)
        print(colored("Successfully generated markdown", "green"))
        print(colored(f"Generated content length: {len(markdown_content)} characters", "blue"))
        return {"content": markdown_content}
    except Exception as e:
        print(colored(f"Error in generate endpoint: {str(e)}", "red"))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if processor:
            await processor.close()

if __name__ == "__main__":
    import uvicorn
    print(colored("Starting Documentation Compiler server...", "green"))
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_includes=["*.py", "*.html"],  # Only watch Python and HTML files
        reload_excludes=[".*", "*.pyc", "__pycache__"],  # Exclude hidden files and cache
        log_level="error",  # Reduce logging noise
        ws_ping_interval=None,  # Disable WebSocket ping
        ws_ping_timeout=None,  # Disable WebSocket timeout
    ) 