import os


class SemanticRouter:
    def __init__(self, client, model_id: str | None = None):
        self.client = client
        self.model_id = model_id or os.getenv("MODEL_GEMINI_FLASH", "gemini-2.5-flash")

    async def evaluate(self, agent_name: str, output: str, transitions: list[dict]) -> str | None:
        if not transitions:
            return None

        options = "\n".join(
            f'{i}. Condição: "{t["condition"]}" -> Destino: {t["target"]}'
            for i, t in enumerate(transitions)
        )

        router_prompt = (
            f"Você é um roteador de fluxo de trabalho especializado. "
            f"Analise o que o agente '{agent_name}' produziu e decida quem deve continuar.\n\n"
            f"SAÍDA DO AGENTE:\n\"\"\"\n{output}\n\"\"\"\n\n"
            f"OPÇÕES DE TRANSIÇÃO:\n{options}\n"
            f"{len(transitions)}. Nenhuma das anteriores -> Destino: null\n\n"
            f"REGRAS:\n"
            f"1. Responda APENAS com o nome exato do Destino ou a palavra 'null'.\n"
            f"2. Nenhum texto adicional além do nome.\n"
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

            print(f"[*] Roteador ({self.model_id}): '{agent_name}' → '{decision}'")

            return None if not decision or decision.lower() == "null" else decision

        except Exception as e:
            print(f"[!] Erro no roteamento semântico: {e}")
            return None
