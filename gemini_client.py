"""
Gemini API client module for Bot Hoster.
Handles all AI calls using Google's Gemini API with per-user API keys.
"""
import json
import logging
import aiohttp
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

API_KEYS_FILE = Path(__file__).parent / "api_keys.json"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Models to try in order (fallback chain)
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.5-flash",
    "gemini-2.0-flash-exp",
]


def load_api_keys() -> Dict[str, str]:
    """Load API keys from JSON file."""
    if not API_KEYS_FILE.exists():
        return {}
    try:
        with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load API keys: {e}")
        return {}


def save_api_keys(keys: Dict[str, str]) -> bool:
    """Save API keys to JSON file."""
    try:
        with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save API keys: {e}")
        return False


def get_user_api_key(user_id: int) -> Optional[str]:
    """Get API key for a specific user, falls back to default."""
    keys = load_api_keys()
    user_key = keys.get(str(user_id))
    if user_key:
        return user_key
    return keys.get("default")


def set_user_api_key(user_id: int, api_key: str) -> bool:
    """Set API key for a specific user."""
    keys = load_api_keys()
    keys[str(user_id)] = api_key
    return save_api_keys(keys)


def has_user_api_key(user_id: int) -> bool:
    """Check if user has their own API key (not relying on default)."""
    keys = load_api_keys()
    return str(user_id) in keys


def parse_gemini_error(status: int, response_text: str) -> str:
    """Parse Gemini API error and return user-friendly message."""
    try:
        data = json.loads(response_text)
        error = data.get("error", {})
        message = error.get("message", "")
        code = error.get("code", status)
        
        if status == 400:
            if "API_KEY_INVALID" in message or "API key not valid" in message:
                return "❌ **Invalid API Key**: Your Gemini API key is invalid. Please check and re-enter it."
            if "INVALID_ARGUMENT" in message:
                return f"❌ **Invalid Request**: {message[:100]}"
            return f"❌ **Bad Request**: {message[:100]}"
        elif status == 401:
            return "❌ **Unauthorized**: Your API key is invalid or has been revoked."
        elif status == 403:
            if "PERMISSION_DENIED" in message:
                return "❌ **Permission Denied**: Your API key doesn't have access to this model."
            if "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
                return "❌ **Quota Exceeded**: Your API key has run out of credits. Get a new key or wait for reset."
            return f"❌ **Forbidden**: {message[:100]}"
        elif status == 429:
            return "⏳ **Rate Limited**: Too many requests. Please wait a moment and try again."
        elif status == 500:
            return "🔧 **Server Error**: Google's servers are having issues. Please try again later."
        elif status == 503:
            return "🔧 **Service Unavailable**: Gemini API is temporarily unavailable. Please try again later."
        else:
            return f"❌ **Error {code}**: {message[:100] if message else 'Unknown error'}"
    except Exception:
        return f"❌ **Error {status}**: Failed to process request. Please try again."


async def call_gemini(
    api_key: str,
    prompt: str,
    timeout: int = 120,
    temperature: float = 0.7
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Call Gemini API with the given prompt, trying multiple models as fallback.
    
    Returns:
        Tuple of (success, content, error_message)
    """
    if not api_key:
        return False, None, "❌ No API key provided."
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192,
        }
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    last_error = None
    
    try:
        async with aiohttp.ClientSession() as session:
            for model in GEMINI_MODELS:
                url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={api_key}"
                logger.info(f"[Gemini] Trying model: {model}")
                
                try:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as response:
                        response_text = await response.text()
                        
                        if response.status == 404:
                            logger.warning(f"[Gemini] Model {model} not found, trying next...")
                            continue
                        
                        if response.status == 429:
                            logger.warning(f"[Gemini] Model {model} rate limited, trying next...")
                            continue
                        
                        if response.status != 200:
                            last_error = parse_gemini_error(response.status, response_text)
                            logger.warning(f"Gemini API error {response.status}: {response_text[:200]}")
                            continue
                        
                        try:
                            data = json.loads(response_text)
                            candidates = data.get("candidates", [])
                            if not candidates:
                                logger.warning(f"[Gemini] Model {model} returned no candidates, trying next...")
                                continue
                            
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            if not parts:
                                continue
                            
                            text = parts[0].get("text", "")
                            if not text:
                                continue
                            
                            logger.info(f"[Gemini] Success with model: {model}")
                            return True, text, None
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse Gemini response: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"[Gemini] Error with model {model}: {e}")
                    continue
            
            # All models failed
            return False, None, last_error or "❌ All AI models failed. Please try again later."
                    
    except aiohttp.ClientError as e:
        logger.error(f"Network error calling Gemini: {e}")
        return False, None, f"❌ **Network Error**: {str(e)[:50]}"
    except TimeoutError:
        return False, None, "⏳ **Timeout**: Request took too long. Please try again."
    except Exception as e:
        logger.error(f"Unexpected error calling Gemini: {e}", exc_info=True)
        return False, None, f"❌ **Error**: {str(e)[:50]}"


async def generate_bot_files(api_key: str, user_prompt: str) -> Tuple[bool, Optional[str], Optional[list], Optional[str]]:
    """
    Generate Discord bot files using Gemini.
    
    Returns:
        Tuple of (success, error_message, files_list, None)
    """
    generation_prompt = (
        "You are an expert Discord bot developer. Generate a Python Discord bot based on the user's request.\n\n"
        "IMPORTANT: Respond ONLY with valid JSON, no markdown, no explanation, no code fences.\n\n"
        "Format:\n"
        '{"files": [{"file_name": "main.py", "content": "..."}, {"file_name": "requirements.txt", "content": "..."}, ...]}\n\n'
        "Required files:\n"
        "- main.py: Main bot code with discord.py\n"
        "- requirements.txt: Dependencies\n"
        "- .env: Environment variables (DISCORD_TOKEN=your_token_here)\n"
        "- README.md: Setup instructions\n\n"
        "Make the code modular, well-commented, and use discord.py 2.0+ with slash commands.\n\n"
        f"User request: {user_prompt}"
    )
    
    success, content, error = await call_gemini(api_key, generation_prompt)
    
    if not success:
        return False, error, None, None
    
    # Parse the JSON response
    try:
        # Clean up response if it has markdown fences
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines if they're fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        
        data = json.loads(text)
        files = data.get("files", [])
        
        if not files:
            return False, "❌ AI returned no files. Please try again.", None, None
        
        # Validate files
        validated = []
        for f in files:
            name = f.get("file_name")
            content = f.get("content", "")
            if name:
                # Security check
                if ".." in name or name.startswith("/"):
                    continue
                validated.append({"file_name": name, "content": content})
        
        if not validated:
            return False, "❌ No valid files in response.", None, None
        
        return True, None, validated, None
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse generated files JSON: {e}")
        logger.debug(f"Raw content: {content[:500]}")
        return False, "❌ AI returned invalid JSON. Please try again.", None, None


async def check_for_error(api_key: str, console_output: str) -> Tuple[bool, Optional[bool], Optional[str]]:
    """
    Check if console output contains an error.
    
    Returns:
        Tuple of (success, is_error, error_message)
    """
    prompt = (
        "Analyze this console output. Is it an error that needs fixing?\n"
        "Respond ONLY with JSON: {\"is_error\": true} or {\"is_error\": false}\n"
        "No explanation, just JSON.\n\n"
        f"Console output:\n{console_output[:2000]}"
    )
    
    success, content, error = await call_gemini(api_key, prompt, timeout=30)
    
    if not success:
        return False, None, error
    
    try:
        text = content.strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) > 1:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        
        data = json.loads(text.strip())
        is_error = data.get("is_error", False)
        return True, is_error, None
    except Exception:
        # If parsing fails, check for error keywords
        lower = console_output.lower()
        is_error = any(kw in lower for kw in ["error", "exception", "traceback", "failed"])
        return True, is_error, None


async def fix_bot_errors(api_key: str, files: list, console_output: str) -> Tuple[bool, Optional[str], Optional[list]]:
    """
    Ask AI to fix code errors.
    
    Returns:
        Tuple of (success, error_or_statement, fixed_files)
    """
    files_json = json.dumps({"files": files, "error": console_output[:3000]})
    
    prompt = (
        "You are a Discord bot error fixer. Fix the errors in this code.\n\n"
        "IMPORTANT: Respond ONLY with valid JSON, no markdown, no explanation.\n\n"
        "Format:\n"
        '{"files": [{"file_name": "main.py", "content": "FULL fixed code"}], "statement": "brief explanation"}\n\n'
        "Rules:\n"
        "- Provide COMPLETE file contents, not partial\n"
        "- Only include files that need changes\n"
        "- If error is about .env values, just provide statement explaining what user needs to fix\n\n"
        f"Payload:\n{files_json}"
    )
    
    success, content, error = await call_gemini(api_key, prompt)
    
    if not success:
        return False, error, None
    
    try:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        
        data = json.loads(text)
        files = data.get("files", [])
        statement = data.get("statement", "")
        
        if files:
            validated = []
            for f in files:
                name = f.get("file_name")
                content = f.get("content", "")
                if name and ".." not in name and not name.startswith("/"):
                    validated.append({"file_name": name, "content": content})
            return True, statement, validated
        elif statement:
            return True, statement, []
        else:
            return False, "❌ AI returned empty response.", None
            
    except json.JSONDecodeError:
        return False, "❌ AI returned invalid JSON. Please try again.", None


async def scan_code_for_security(api_key: str, file_path: str, file_content: str) -> Dict[str, Any]:
    """
    Scan code for security issues.
    
    Returns:
        Dict with 'type' ('malicious' or 'normal') and 'statement'
    """
    prompt = (
        "You are a security assistant. Check this code for malicious behavior.\n\n"
        "Flag as MALICIOUS if it:\n"
        "- Executes shell/system commands (os.system, subprocess, exec, eval)\n"
        "- Accesses files outside project directory\n"
        "- Attempts privilege escalation\n"
        "- Uses obfuscated code to hide intent\n\n"
        "Mark as NORMAL if it's:\n"
        "- Standard Discord bot code\n"
        "- Contains hardcoded tokens (allowed)\n"
        "- Normal file operations within project\n\n"
        'Respond ONLY with JSON: {"type": "malicious" or "normal", "statement": "brief reason"}\n\n'
        f"File: {file_path}\n"
        f"Code:\n{file_content[:5000]}"
    )
    
    success, content, error = await call_gemini(api_key, prompt, timeout=30, temperature=0.1)
    
    if not success:
        logger.warning(f"Security scan failed for {file_path}: {error}")
        return {"type": "normal", "statement": "Security scan unavailable"}
    
    try:
        text = content.strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) > 1:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        
        data = json.loads(text.strip())
        return {
            "type": data.get("type", "normal"),
            "statement": data.get("statement", "")
        }
    except Exception:
        # If parsing fails, check for malicious keyword
        if "malicious" in content.lower():
            return {"type": "malicious", "statement": "Potential malicious code detected"}
        return {"type": "normal", "statement": "Code appears safe"}

