import os, httpx

async def generate_explanation(prompt: str) -> str | None:
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434')
    model=os.getenv('OLLAMA_MODEL','llama3.2')
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r=await client.post(f'{base}/api/generate',json={'model':model,'prompt':prompt,'stream':False})
            r.raise_for_status()
            return r.json().get('response')
    except Exception:
        return None
