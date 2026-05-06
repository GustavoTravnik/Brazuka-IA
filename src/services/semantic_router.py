import os
from anthropic import AuthenticationError, PermissionDeniedError, APIStatusError

class SemanticRouter:
    def __init__(self, client, model_id: str | None = None):
        self.client = client
        self.model_id = model_id or os.getenv("MODEL_HAIKU", "claude-haiku-4-5")

    async def evaluate(self, agent_name: str, output: str, transitions: list[dict]) -> str | None:
        if not transitions:
            return None

        options = "\n".join(
            f'{i}. Condition: "{t["condition"]}" -> Target: {t["target"]}'
            for i, t in enumerate(transitions)
        )

        router_prompt = (
            f"Workflow router. Agent '{agent_name}' produced the output below.\n"
            f"Choose the next target based on the transition conditions.\n\n"
            f"OUTPUT:\n\"\"\"\n{output}\n\"\"\"\n\n"
            f"TRANSITIONS:\n{options}\n"
            f"{len(transitions)}. None of the above -> Target: null\n\n"
            f"Reply with ONLY the exact Target name or 'null'. No extra text.\n"
        )

        try:
            async with self.client.messages.stream(
                model=self.model_id,
                max_tokens=50,
                messages=[{"role": "user", "content": router_prompt}],
            ) as stream:
                resp = await stream.get_final_message()

            raw_decision = resp.content[0].text.strip() if resp.content else ""
            decision = raw_decision.strip("'\"").strip()

            print(f"[*] Router ({self.model_id}): '{agent_name}' → '{decision}'")

            return None if not decision or decision.lower() == "null" else decision

        except (AuthenticationError, PermissionDeniedError) as e:
            raise
        except APIStatusError as e:
            if e.status_code in (401, 403):
                raise
            print(f"[!] Semantic router error: {e}")
            return None
        except Exception as e:
            print(f"[!] Semantic router error: {e}")
            return None
