"""
Bytez API client module for Bot Hoster.
Handles all AI calls using Bytez API with per-user API keys.
"""
import json
import logging
import aiohttp
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)

API_KEYS_FILE = Path(__file__).parent / "api_keys.json"
BYTEZ_API_BASE = "https://api.bytez.com/models/v2"

# Default API key
DEFAULT_API_KEY = "f9bbcb752b8eb9f814336cb6c84839b9"

# Models to try in order (fallback chain)
BYTEZ_MODELS = [
    "Qwen/Qwen3-4B-Instruct-2507",
    "microsoft/Phi-3-mini-4k-instruct",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
]


def load_api_keys() -> Dict[str, str]:
    """Load API keys from JSON file."""
    if not API_KEYS_FILE.exists():
        return {"default": DEFAULT_API_KEY}
    try:
        with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "default" not in data:
                data["default"] = DEFAULT_API_KEY
            return data
    except Exception as e:
        logger.error(f"Failed to load API keys: {e}")
        return {"default": DEFAULT_API_KEY}


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
    return keys.get("default", DEFAULT_API_KEY)


def set_user_api_key(user_id: int, api_key: str) -> bool:
    """Set API key for a specific user."""
    keys = load_api_keys()
    keys[str(user_id)] = api_key
    return save_api_keys(keys)


def has_user_api_key(user_id: int) -> bool:
    """Check if user has their own API key (not relying on default)."""
    keys = load_api_keys()
    return str(user_id) in keys


def parse_bytez_error(status: int, response_text: str) -> str:
    """Parse Bytez API error and return user-friendly message."""
    try:
        data = json.loads(response_text)
        error = data.get("error", "")
        
        if status == 400:
            return f"❌ **Bad Request**: {str(error)[:100]}"
        elif status == 401:
            return "❌ **Unauthorized**: Your API key is invalid."
        elif status == 403:
            return "❌ **Forbidden**: Access denied."
        elif status == 429:
            return "⏳ **Rate Limited**: Too many requests. Please wait and try again."
        elif status == 500:
            return "🔧 **Server Error**: Bytez servers are having issues. Please try again later."
        elif status == 503:
            return "🔧 **Service Unavailable**: API is temporarily unavailable."
        else:
            return f"❌ **Error {status}**: {str(error)[:100] if error else 'Unknown error'}"
    except Exception:
        return f"❌ **Error {status}**: Failed to process request."


async def call_bytez(
    api_key: str,
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    timeout: int = 120
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Call Bytez API with the given prompt, trying multiple models as fallback.
    
    Returns:
        Tuple of (success, content, error_message)
    """
    if not api_key:
        api_key = DEFAULT_API_KEY
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"
    }
    
    last_error = None
    
    try:
        async with aiohttp.ClientSession() as session:
            for model in BYTEZ_MODELS:
                logger.info(f"[Bytez] Trying model: {model}")
                url = f"{BYTEZ_API_BASE}/{model}"
                
                payload = {
                    "messages": messages,
                    "params": {
                        "max_new_tokens": 8192
                    }
                }
                
                try:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as response:
                        response_text = await response.text()
                        
                        if response.status == 429:
                            logger.warning(f"[Bytez] Model {model} rate limited, trying next...")
                            last_error = "⏳ Rate limited. Please wait and try again."
                            continue
                        
                        if response.status != 200:
                            last_error = parse_bytez_error(response.status, response_text)
                            logger.warning(f"Bytez API error {response.status}: {response_text[:200]}")
                            continue
                        
                        try:
                            data = json.loads(response_text)
                            
                            # Handle different response formats
                            output = data.get("output")
                            if output:
                                text = None
                                # If output is a dict with role/content (single message)
                                if isinstance(output, dict) and output.get("role") == "assistant":
                                    text = output.get("content", "")
                                # If output is a list, get the last assistant message
                                elif isinstance(output, list):
                                    for item in reversed(output):
                                        if isinstance(item, dict) and item.get("role") == "assistant":
                                            text = item.get("content", "")
                                            break
                                elif isinstance(output, str):
                                    text = output
                                
                                if text:
                                    logger.info(f"[Bytez] Success with model: {model}")
                                    return True, text, None
                            
                            # Check for error in response
                            error = data.get("error")
                            if error:
                                logger.warning(f"[Bytez] Model {model} returned error: {error}")
                                last_error = f"❌ {error}"
                                continue
                            
                            logger.warning(f"[Bytez] Model {model} returned empty response")
                            continue
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse Bytez response: {e}")
                            continue
                            
                except Exception as e:
                    logger.warning(f"[Bytez] Error with model {model}: {e}")
                    continue
            
            # All models failed
            return False, None, last_error or "❌ All AI models failed. Please try again later."
                    
    except aiohttp.ClientError as e:
        logger.error(f"Network error calling Bytez: {e}")
        return False, None, f"❌ **Network Error**: {str(e)[:50]}"
    except TimeoutError:
        return False, None, "⏳ **Timeout**: Request took too long. Please try again."
    except Exception as e:
        logger.error(f"Unexpected error calling Bytez: {e}", exc_info=True)
        return False, None, f"❌ **Error**: {str(e)[:50]}"


async def generate_bot_files(api_key: str, user_prompt: str) -> Tuple[bool, Optional[str], Optional[list], Optional[str]]:
    """
    Generate Discord bot files using Bytez.
    
    Returns:
        Tuple of (success, error_message, files_list, None)
    """
    system_prompt = "You are an expert Discord bot developer. You always respond with valid JSON only, no markdown, no explanation."
    
    generation_prompt = (
        "Generate a Python Discord bot based on the user's request.\n\n"
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
    
    success, content, error = await call_bytez(api_key, generation_prompt, system_prompt)
    
    if not success:
        return False, error, None, None
    
    # Parse the JSON response
    try:
        # Clean up response if it has markdown fences
        text = content.strip()
        logger.debug(f"Raw AI response (first 500 chars): {text[:500]}")
        
        # Remove thinking tags if present (Qwen models)
        if "<think>" in text:
            think_end = text.find("</think>")
            if think_end != -1:
                text = text[think_end + 8:].strip()
        
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        
        # Try to find JSON in the response
        start_idx = text.find('{"files"')
        if start_idx == -1:
            start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx]
        
        logger.debug(f"Cleaned JSON (first 500 chars): {text[:500]}")
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
        logger.warning(f"Raw content (first 1000 chars): {content[:1000]}")
        return False, "❌ AI returned invalid JSON. Please try again.", None, None


async def check_for_error(api_key: str, console_output: str) -> Tuple[bool, Optional[bool], Optional[str]]:
    """
    Check if console output contains an error.
    
    Returns:
        Tuple of (success, is_error, error_message)
    """
    system_prompt = "You are an error analyzer. Respond only with JSON."
    
    prompt = (
        "Analyze this console output. Is it an error that needs fixing?\n"
        "Respond ONLY with JSON: {\"is_error\": true} or {\"is_error\": false}\n"
        "No explanation, just JSON.\n\n"
        f"Console output:\n{console_output[:2000]}"
    )
    
    success, content, error = await call_bytez(api_key, prompt, system_prompt, timeout=30)
    
    if not success:
        return False, None, error
    
    try:
        text = content.strip()
        # Find JSON in response
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx]
        
        data = json.loads(text)
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
    system_prompt = "You are a Discord bot error fixer. Respond only with valid JSON."
    
    files_json = json.dumps({"files": files, "error": console_output[:3000]})
    
    prompt = (
        "Fix the errors in this Discord bot code.\n\n"
        "IMPORTANT: Respond ONLY with valid JSON, no markdown, no explanation.\n\n"
        "Format:\n"
        '{"files": [{"file_name": "main.py", "content": "FULL fixed code"}], "statement": "brief explanation"}\n\n'
        "Rules:\n"
        "- Provide COMPLETE file contents, not partial\n"
        "- Only include files that need changes\n"
        "- If error is about .env values, just provide statement explaining what user needs to fix\n\n"
        f"Payload:\n{files_json}"
    )
    
    success, content, error = await call_bytez(api_key, prompt, system_prompt)
    
    if not success:
        return False, error, None
    
    try:
        text = content.strip()
        # Find JSON in response
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx]
        
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
    system_prompt = "You are a security analyzer. Respond only with JSON."
    
    prompt = (
        "Check this code for malicious behavior.\n\n"
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
    
    success, content, error = await call_bytez(api_key, prompt, system_prompt, timeout=30)
    
    if not success:
        logger.warning(f"Security scan failed for {file_path}: {error}")
        return {"type": "normal", "statement": "Security scan unavailable"}
    
    try:
        text = content.strip()
        # Find JSON in response
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx]
        
        data = json.loads(text)
        return {
            "type": data.get("type", "normal"),
            "statement": data.get("statement", "")
        }
    except Exception:
        # If parsing fails, check for malicious keyword
        if "malicious" in content.lower():
            return {"type": "malicious", "statement": "Potential malicious code detected"}
        return {"type": "normal", "statement": "Code appears safe"}

