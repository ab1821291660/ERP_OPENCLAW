import os
import json
import logging
import sys
from dotenv import load_dotenv
# from fastapi import FastAPI, Request
# import uvicorn
from deepagents import create_deep_agent
# from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Load environment ===
load_dotenv()
# === Config ===
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20B")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
DEFAULT_MODEL_PROVIDER = os.getenv("DEFAULT_MODEL_PROVIDER", "ollama")
##
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", 25))
PORT = int(os.getenv("SERVER_PORT", 8000))


def _______(self):pass
from langchain_core.tools import tool
import json
import yfinance as yf
import logging
from langchain_community.tools import BraveSearch
from tavily import TavilyClient
import os
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()

# Default: no search
web_search = None
if BRAVE_SEARCH_API_KEY:
    brave_search = BraveSearch.from_api_key(
        api_key=BRAVE_SEARCH_API_KEY,
        search_kwargs={"count": 3}
    )


    def web_search_func(query: str):
        return brave_search.run(query)


    web_search = web_search_func
    SEARCH_PROVIDER = "brave"

    logging.info("✅ Using Brave Search as web_search")

elif TAVILY_API_KEY:
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)


    def web_search_func(query: str, max_results: int = 5):
        return tavily_client.search(query, max_results=max_results)


    web_search = web_search_func
    SEARCH_PROVIDER = "tavily"

    logging.info("✅ Using Tavily Search as web_search")

else:
    logging.warning("⚠️ No search provider configured. web_search will be None")


@tool
def get_stock_price(symbol: str) -> str:
    """Get current stock price and basic information."""
    logging.info(f"[TOOL] Fetching stock price for: {symbol}")
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        hist = stock.history(period="1mo")
        if hist.empty:
            return json.dumps({"error": f"Could not retrieve data for {symbol}"})

        current_price = hist['Close'].iloc[-1]
        result = {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "company_name": info.get('longName', symbol),
            "market_cap": info.get('marketCap', 0),
            "pe_ratio": info.get('trailingPE', 'N/A'),
            "52_week_high": info.get('fiftyTwoWeekHigh', 0),
            "52_week_low": info.get('fiftyTwoWeekLow', 0)
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        logging.exception("Exception in get_stock_price")
        return json.dumps({"error": str(e)})


@tool
def get_financial_statements(symbol: str) -> str:
    """Retrieve key financial statement data."""
    try:
        stock = yf.Ticker(symbol)
        financials = stock.financials
        balance_sheet = stock.balance_sheet
        latest_year = financials.columns[0]

        return json.dumps(
            {
                "symbol": symbol,
                "period": str(latest_year.year),
                "revenue": (
                    float(financials.loc["Total Revenue", latest_year])
                    if "Total Revenue" in financials.index
                    else "N/A"
                ),
                "net_income": (
                    float(financials.loc["Net Income", latest_year])
                    if "Net Income" in financials.index
                    else "N/A"
                ),
                "total_assets": (
                    float(balance_sheet.loc["Total Assets", latest_year])
                    if "Total Assets" in balance_sheet.index
                    else "N/A"
                ),
                "total_debt": (
                    float(balance_sheet.loc["Total Debt", latest_year])
                    if "Total Debt" in balance_sheet.index
                    else "N/A"
                ),
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def search_market_trends(topic: str) -> str:
    """Search for market trends and analysis on a specific topic using Brave or Tavily Search."""
    if not web_search:
        return json.dumps({"error": "No search provider configured"})

    try:
        search_query = f"{topic} market analysis trends 2024 2025 investment outlook forecast"
        results = web_search(search_query)  # 👈 unified function

        return json.dumps({
            "topic": topic,
            "search_query": search_query,
            "trend_results": results
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to search trends: {str(e)}"})


@tool
def search_financial_news(company_name: str, symbol: str) -> str:
    """Search for recent financial news about a company using Brave/ Tavily Search.
    Call this tool ONLY ONCE per query, unless specifically asked for additional news.
    If news results are already available, do not call again."""
    if not web_search:
        return json.dumps({"error": "No search provider configured"})

    try:
        query = f"{company_name} {symbol} financial news stock earnings latest"
        results = web_search(query)  # 👈 unified call
        return json.dumps({
            "symbol": symbol,
            "company": company_name,
            "results": results
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def get_technical_indicators(symbol: str, period: str = "3mo") -> str:
    """Calculate key technical indicators."""
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)
        if hist.empty:
            return json.dumps({"error": f"No historical data for {symbol}"})

        hist["SMA_20"] = hist["Close"].rolling(window=20).mean()
        hist["SMA_50"] = hist["Close"].rolling(window=50).mean()

        delta = hist["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        latest = hist.iloc[-1]
        latest_rsi = rsi.iloc[-1]

        return json.dumps(
            {
                "symbol": symbol,
                "current_price": round(latest["Close"], 2),
                "sma_20": round(latest["SMA_20"], 2),
                "sma_50": round(latest["SMA_50"], 2),
                "rsi": round(latest_rsi, 2),
                "volume": int(latest["Volume"]),
                "trend_signal": (
                    "bullish"
                    if latest["Close"] > latest["SMA_20"] > latest["SMA_50"]
                    else "bearish"
                ),
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def ________(self):pass
# === Load core instructions ===
# with open("instructions.md", "r") as f:
#     CORE_INSTRUCTIONS = f.read()
CORE_INSTRUCTIONS = '''You are a stock research agent with tools + sub-agents.

# Available Tools
- get_stock_price(symbol): Fetch current stock price, company name, market cap, P/E ratio, and 52-week range.
- get_financial_statements(symbol): Retrieve revenue, net income, assets, and debt from the latest financial statements.
- get_technical_indicators(symbol, period="3mo"): Calculate SMA (20/50), RSI, volume, and generate trend signals (bullish/bearish).
- search_financial_news(company_name, symbol): Search recent company-specific financial news, earnings, and market updates.
- search_market_trends(topic): Search broader market/sector trends and investment outlook.

# Sub-Agents
- Fundamental Analyst: Focuses on company financials, valuation ratios, growth vs peers, intrinsic value.
- Technical Analyst: Focuses on price trends, indicators, support/resistance, entry/exit signals.
- Risk Analyst: Focuses on systemic, sector, and company-specific risks, plus mitigation strategies.

# Output Rules
- Tool calls → ONLY JSON (no markdown, no text).
- Final report → Markdown with sections (Financials, Technicals, Risks, Recommendation).
- Do not mix JSON + Markdown in one response.

# Workflow
1. Gather stock basics & price
2. Get recent company news (once)
3. Fundamental analysis
4. Technical analysis
5. Risk assessment
6. Compare with peers if relevant
7. Synthesize into investment thesis
8. Conclude with Buy/Sell/Hold + price targets

# Stock Research Report – {company} ({symbol})

## 1. Company Snapshot
...

## 2. Recent News
...

## 3. Fundamentals
...

## 4. Technicals
...

## 5. Risks
...

## 6. Competitive Landscape
...

## 7. Investment Thesis
...

## 8. Recommendation
**Verdict:** Buy/Sell/Hold  
**Target Price:** $XXX – $YYY (3-month horizon)'''


# === Load subagents ===
# with open("subagents.json", "r") as f:
#     subagents_config = json.load(f)
f = {
  "fundamental_analyst": {
    "name": "fundamental-analyst",
    "description": "Performs company fundamental analysis",
    "prompt": "You are a fundamental analyst. Focus only on:\n- Financial statements (Revenue, Net Income, Assets, Debt)\n- Ratios: P/E, P/B, ROE, ROA, Debt/Equity\n- Growth trends vs peers\n- Valuation (intrinsic value)"
  },
  "technical_analyst": {
    "name": "technical-analyst",
    "description": "Analyzes technical signals",
    "prompt": "You are a technical analyst. Focus only on:\n- Price trends and patterns\n- Indicators: RSI, MACD, MA, Bollinger Bands\n- Support/resistance levels\n- Short-term entry/exit signals"
  },
  "risk_analyst": {
    "name": "risk-analyst",
    "description": "Assesses investment risks",
    "prompt": "You are a risk analyst. Focus only on:\n- Market/systemic risks\n- Company-specific risks\n- Sector/industry risks\n- Credit/liquidity/regulatory factors\n- Mitigation strategies"
  }
}
subagents_config = json.load(f)
fundamental_analyst = subagents_config["fundamental_analyst"]
technical_analyst = subagents_config["technical_analyst"]
risk_analyst = subagents_config["risk_analyst"]


# === Tools ===
tools = [get_stock_price, get_financial_statements, get_technical_indicators]
if web_search:
    tools.extend([search_financial_news, search_market_trends])
else:
    logging.warning("⚠️ Web search disabled (no Brave/Tavily API key found).")


# === Model ===
model = ChatOllama(model=OLLAMA_MODEL, temperature=0)
# === Create DeepAgent ===
agent = create_deep_agent(
    model=model,
    instructions=CORE_INSTRUCTIONS,

    tools=tools,

    subagents=[fundamental_analyst, technical_analyst, risk_analyst],
).with_config({"recursion_limit": RECURSION_LIMIT})##===================================



# {
#   "dependencies": ["."],
#   "graphs": {
#     "research": "./---- research-agents-v3【sagar-n股票工具】----deepagents.py:agent"
#   },
#   "env": ".env"
# }
# 🧠 Deep Research Agents — Version 3 (V3) Setup Guide
# This guide explains how to start the **LangSmith server** for Deep Research Agents V3 and connect it with the **Deep Agents UI**.
#
# ---
#
# ## ▶️ How to Run
#
# 1. **Clone the repository:**
#
# ```bash
# git clone https://github.com/sagar-n/deepagents.git
# cd deep-research-agents-v3
# ```
#
# 2. **Create and activate a virtual environment:**
#
# ```bash
# python -m venv venv
# source venv/bin/activate   # On macOS/Linux
# venv\Scripts\activate      # On Windows
# ```
#
# 3. **Install dependencies:**
#
# ```bash
# pip install -r requirements.txt
# ```
#
# 4. **Set up your `.env` file:**
#
# ```env
# TAVILY_API_KEY=your_tavily_key_here
# BRAVE_SEARCH_API_KEY=your_brave_key_here
# OLLAMA_MODEL=gpt-oss:20B
# LM_STUDIO_MODEL=local-model
# LM_STUDIO_BASE_URL=http://localhost:1234/v1
# LM_STUDIO_API_KEY=lm-studio
# DEFAULT_MODEL_PROVIDER=ollama
# RECURSION_LIMIT = 30
# ```
#
# 5. **Run the app:**
#
#
# Start the LangGraph backend:
#
# ```bash
# langgraph dev
# ```
#
# The **LangSmith server** will launch at [http://127.0.0.1:2024/](http://127.0.0.1:2024/)
#
# ---
#
# ### 6. Set Up the Deep Agents UI
#
# 1. Clone the UI repository:
#    ```bash
#    git clone https://github.com/langchain-ai/deep-agents-ui.git
#    cd deep-agents-ui
#    ```
#
# 2. Create a `.env.local` file in the root of the UI project and add the following:
#    ```bash
#    NEXT_PUBLIC_DEPLOYMENT_URL="http://127.0.0.1:2024"  # Or your LangGraph server URL
#    NEXT_PUBLIC_AGENT_ID=research
#    ```
#
# 3. Install dependencies:
#    ```bash
#    npm install
#    ```
#
# 4. Start the UI in development mode:
#    ```bash
#    npm run dev
#    ```
#
#    The frontend will be available at [http://localhost:3000](http://localhost:3000)
#
