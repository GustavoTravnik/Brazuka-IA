"""
tool_router.py — v1.0
=====================
Decide em tempo zero (sem chamada de API) se a mensagem do usuário
precisa ou não das tool definitions no payload enviado à Anthropic.

Motivação
─────────
As 6 tool definitions nativas custam ~1 350 tokens de input em TODA
chamada — independentemente de o usuário pedir algo simples como "1+2".
Para conversas que não envolvem acesso a arquivos, shell ou código,
enviar as tools é desperdício puro.

Estratégia
──────────
Classificação por dois vetores complementares:
  1. SINAIS POSITIVOS (precisa de tools):
     Palavras-chave que indicam intenção técnica clara — crie, leia,
     abra arquivo, rode comando, busque no código, etc.

  2. SINAIS NEGATIVOS (não precisa de tools):
     Padrões que indicam conversa, pergunta conceitual, cálculo,
     tradução, resumo — onde tools seriam irrelevantes.

  O classificador retorna True (precisa) se:
    a) qualquer sinal POSITIVO for encontrado, OU
    b) nenhum sinal NEGATIVO for encontrado (dúvida → conservador).

  Retorna False (não precisa) somente quando há sinais NEGATIVOS
  claros e NENHUM sinal POSITIVO.

Uso em app.py
─────────────
    from controllers.tool_router import needs_tools

    tools_to_send = active_tools if needs_tools(user_text, history) else []

    resp = client.messages.stream(
        tools=tools_to_send,
        ...
    )

Notas
─────
- Falso positivo (envia tools quando não precisava) → custo extra, sem dano funcional.
- Falso negativo (omite tools quando precisava)     → IA não pode usar tools naquele turno.
Por segurança, os limiares são conservadores: prefere falso positivo.
- Dentro de um ciclo ativo de tool calls (há tool_use no histórico recente)
  o router sempre retorna True — a IA pode precisar de mais tools para concluir.
"""

from __future__ import annotations

import re

_POSITIVE_PATTERNS: list[str] = [
    r"\barquivo\b", r"\bfile\b", r"\bpasta\b", r"\bdiretório\b", r"\bdirectory\b",
    r"\bfolder\b", r"\bleia\b", r"\bler\b", r"\bread\b", r"\bwrite\b", r"\bescrev",
    r"\bcriar?\b", r"\bcrie\b", r"\bcreate\b", r"\bsalvar?\b", r"\bsave\b",
    r"\beditar?\b", r"\bedit\b", r"\bpatch\b", r"\bmodificar?\b", r"\bmodify\b",
    r"\bapagar?\b", r"\bdelete\b", r"\bremov", r"\batuali[zs]",
    r"\blist[ae]\b", r"\blistar\b", r"\blistagem\b",
    r"\bcódigo\b", r"\bcode\b", r"\bimplementa", r"\bimplementation\b",
    r"\bfunção\b", r"\bfunction\b", r"\bclasse\b", r"\bclass\b", r"\bmódulo\b",
    r"\bmodule\b", r"\bprojeto\b", r"\bproject\b", r"\brepositório\b", r"\brepo\b",
    r"\bpackage\b", r"\bimport\b", r"\bdependência\b", r"\bdependency\b",
    r"\bconfigura", r"\bconfig\b", r"\bsetup\b", r"\binstala",
    r"\bcomando\b", r"\bcommand\b", r"\bshell\b", r"\bterminal\b",
    r"\bexecut", r"\brodar?\b", r"\brun\b", r"\bbuild\b", r"\bcompil",
    r"\bteste[s]?\b", r"\btest[s]?\b", r"\bdeploy\b",
    r"\bbuscar?\b", r"\bsearch\b", r"\bgrep\b", r"\bencontrar?\b", r"\bfind\b",
    r"\bprocurar?\b", r"\banalisar?\b", r"\banalyze\b", r"\binvestigar?\b",
    r"\bverificar?\b", r"\bcheck\b", r"\bdebugar?\b", r"\bdebug\b",
    r"\bimportar?\b", r"\bclonar?\b", r"\bclone\b",
    r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b", r"\bpull\b",
    r"\bpush\b", r"\bdiff\b", r"\bstash\b",
    r"\b\w+\.(py|ts|js|jsx|tsx|json|yaml|yml|md|txt|sh|bash|go|rs|kt|swift|cs|java|env|toml|tf|sql|html|css|xml|proto)\b",
    r"(?:^|[\s\"'])(?:/|~/|\./)[^\s\"']+",
]

_NEGATIVE_PATTERNS: list[str] = [
    r"^\s*[\d\s\+\-\*\/\^\(\)\.]+\s*[=\?]?\s*$",                              
    r"\bcalcul",
    r"\bquanto\s+[éeè]\b",                                                         
    r"\bsomar?\b", r"\bsoma\b", r"\bsubtrai", r"\bmultiplicar?\b", r"\bdividir?\b",
    r"\bequação\b", r"\bequation\b", r"\bfórmula\b", r"\bformula\b",
    r"\bo que é\b", r"\bwhat is\b", r"\bwhat are\b", r"\bexplain\b",
    r"\bexplique\b", r"\bme explica\b", r"\bcomo funciona\b", r"\bhow does\b",
    r"\bpor que\b", r"\bwhy\b", r"\bquando\b", r"\bwhen\b", r"\bonde\b",
    r"\bwhere\b", r"\bquem\b", r"\bwho\b", r"\bqual\b", r"\bwhich\b",
    r"\btraduz", r"\btranslat", r"\bresuma", r"\bsummariz", r"\bresumo\b",
    r"\bparafrase", r"\bparaphrase", r"\bcorrig", r"\brevisar?\b", r"\brevis",
    r"\bortografi", r"\bgramátic", r"\bgrammar\b",
    r"^(oi|olá|hello|hi|hey|bom dia|boa tarde|boa noite|tudo bem|ok|okay|obrigad)[!\.\?,\s]",
    r"^\s*(sim|não|yes|no|talvez|maybe|claro|sure)\s*[!\.\?]?\s*$",
    r"\btudo\s+bem\b", r"\bcomo\s+vai\b", r"\bboa\s+(tarde|noite|dia)\b",
    r"\bpiada\b", r"\bjoke\b", r"\bstory\b", r"\bhistória\b",
    r"\bdefin", r"\bconceito\b", r"\bconcept\b", r"\bdiferença entre\b",
    r"\bdifference between\b", r"\bvantagem\b", r"\badvantage\b",
    r"\bdesvantagem\b", r"\bdisadvantage\b", r"\bcomparar?\b", r"\bcompar",
]

_POS_RE: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _POSITIVE_PATTERNS
]
_NEG_RE: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _NEGATIVE_PATTERNS
]

def _has_active_tool_cycle(history: list[dict]) -> bool:
    """
    Verifica se o histórico recente contém um ciclo de tools em andamento.
    Detecta mensagens assistant com tool_use nas últimas 4 entradas.
    Se sim, o router deve sempre retornar True — a IA pode precisar de
    mais tools para concluir a tarefa.
    """
    for msg in history[-4:]:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                return True
    return False

def needs_tools(user_text: str, history: list[dict] | None = None) -> bool:
    """
    Retorna True se a mensagem provavelmente exige tool definitions no payload.
    Retorna False se é conversa/cálculo simples — economiza ~1 350 tokens de input.

    Parâmetros
    ──────────
    user_text : texto digitado pelo usuário (já resolvido de comandos /slash).
    history   : histórico de mensagens atual (detecta ciclo de tool ativo).

    Lógica
    ──────
    1. Ciclo de tool ativo no histórico recente → True (conservador).
    2. Qualquer sinal POSITIVO no texto         → True.
    3. Nenhum sinal NEGATIVO                    → True (texto neutro/ambíguo).
    4. Apenas sinais NEGATIVOS, sem positivos   → False.
    """
    text = (user_text or "").strip()

    if history and _has_active_tool_cycle(history):
        return True

    for pat in _POS_RE:
        if pat.search(text):
            return True

    for pat in _NEG_RE:
        if pat.search(text):
            return False                                                         
    return True
