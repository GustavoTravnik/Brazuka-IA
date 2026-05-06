"""
tool_rag.py — v2.0
===================
RAG de tools: seleciona dinamicamente quais tool definitions enviar à API
com base na similaridade semântica entre a mensagem do usuário e as
descrições das tools disponíveis.

Motivação
─────────
O `tool_router.py` usa regex para decidir "envia tools ou não" — binário.
O Tool RAG vai além: seleciona QUAIS tools enviar, evitando poluir o
contexto com definições irrelevantes para a tarefa atual.

Exemplo:
  Usuário: "busca no código onde está o método Login"
  Sem RAG  → envia 10 nativas + N MCPs (potencialmente 50+ tools)
  Com RAG  → envia apenas: search_text, navigate_symbols  ✅

v2.0 — Mudanças de economia de tokens
──────────────────────────────────────
  - MAX_K (teto) substitui DEFAULT_K (alvo fixo): não mais "sempre 5".
  - MIN_SCORE subiu de 0.10 → 0.25: tools com score baixo não são enviadas.
  - Nova constante HIGH_SCORE (0.35): tools acima disso sempre entram.
  - Lógica agora é threshold-first: inclui apenas tools acima de MIN_SCORE,
    até o limite de MAX_K. Resultado pode ser 1, 2, 3... até MAX_K.
  - Novo método select_for_cycle(): para ciclos de tool_use, envia apenas
    as tools que a IA realmente usou no turno anterior + vizinhas por RAG,
    em vez de enviar TODAS as tools (que era o maior desperdício).

Funcionamento
─────────────
1. Todas as tools (nativas + MCP) têm suas descrições indexadas via embeddings.
2. A mensagem do usuário é transformada em embedding.
3. Cosine similarity ranqueia as tools mais relevantes.
4. Apenas tools acima do score mínimo são enviadas, até o teto de MAX_K.

Embedding local (sem custo de API)
───────────────────────────────────
Usa `sentence-transformers` com o modelo `all-MiniLM-L6-v2` (~80MB).
- Sem latência de rede (roda local).
- Sem custo por token.
- Qualidade suficiente para matching de descrições curtas de tools.

Fallback
────────
Se `sentence-transformers` não estiver instalado, o ToolRAG cai no
comportamento legado: retorna todas as tools sem filtragem, com aviso.

Cache
─────
Os embeddings das tools são calculados UMA vez e cacheados em memória.
Re-indexa automaticamente se o conjunto de tools mudar (ex: novo MCP conectado).

Uso em app.py
─────────────
    from controllers.tool_rag import ToolRAG

    rag = ToolRAG()
    rag.index(active_tools)
    # Turno normal: seleciona por score + teto
    tools_to_send = rag.select(user_text)
    # Ciclo de tool_use: garante tools usadas + vizinhas relevantes
    tools_to_send = rag.select_for_cycle(user_text, used_tool_names={"read_files", "search_text"})
"""

from __future__ import annotations

import math
import warnings
from typing import Sequence
MAX_K            = 6                                                
MIN_SCORE        = 0.25                                            
HIGH_SCORE       = 0.35                                                      
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

_ALWAYS_INCLUDE: frozenset[str] = frozenset()

def _cosine(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno entre dois vetores."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

class ToolRAG:
    """
    Indexador e seletor semântico de tools.

    Ciclo de vida típico:
        rag = ToolRAG()
        rag.index(all_tools)
        tools = rag.select(user_msg)
    """

    def __init__(self, max_k: int = MAX_K, min_score: float = MIN_SCORE) -> None:
        self.max_k = max_k
        self.min_score = min_score

        self._tools: list[dict] = []
        self._tool_name_to_idx: dict[str, int] = {}                          
        self._embeddings: list[list[float]] = []
        self._index_hash: int = 0
        self._model = None
        self._available = False

        self._load_model()

    def _load_model(self) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from sentence_transformers import SentenceTransformer                
            self._model = SentenceTransformer(EMBED_MODEL_NAME)
            self._available = True
            print(f"[🔍 ToolRAG] Modelo de embedding carregado: {EMBED_MODEL_NAME}")
        except ImportError:
            self._available = False
            print(
                "[⚠️  ToolRAG] sentence-transformers não instalado. "
                "Executando sem RAG (todas as tools serão enviadas). "
                "Para ativar: pip install sentence-transformers"
            )

    def _embed(self, text: str) -> list[float]:
        """Gera embedding para um texto. Retorna lista de floats."""
        vec = self._model.encode(text, convert_to_numpy=True, show_progress_bar=False)
        return vec.tolist()

    def index(self, tools: Sequence[dict]) -> None:
        """
        Indexa (ou re-indexa) o conjunto de tools.
        Operação idempotente: só recalcula se o conjunto mudou.
        """
        if not self._available:
            self._tools = list(tools)
            self._tool_name_to_idx = {t["name"]: i for i, t in enumerate(self._tools)}
            return

        new_hash = hash(tuple(t["name"] for t in tools))
        if new_hash == self._index_hash and self._tools:
            return

        self._tools = list(tools)
        self._tool_name_to_idx = {t["name"]: i for i, t in enumerate(self._tools)}
        self._index_hash = new_hash

        texts = [
            f"{t['name']}: {t.get('description', '')}"
            for t in self._tools
        ]

        print(f"[🔍 ToolRAG] Indexando {len(texts)} tools...", end=" ", flush=True)
        self._embeddings = [self._embed(txt) for txt in texts]
        print("✅")

    def _rank(self, user_text: str) -> list[tuple[int, float]]:
        """Retorna lista de (idx, score) ordenada por score decrescente."""
        query_vec = self._embed(user_text)
        scored = [
            (i, _cosine(query_vec, emb))
            for i, emb in enumerate(self._embeddings)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def select(
        self,
        user_text: str,
        max_k: int | None = None,
        always_include: frozenset[str] | None = None,
    ) -> list[dict]:
        """
        Retorna tools relevantes para `user_text`, filtradas por score.

        Lógica (v2.0 — threshold-first):
        1. Calcula score de todas as tools.
        2. Inclui tools com score >= HIGH_SCORE (quase certeza de uso).
        3. Inclui tools com score >= MIN_SCORE (candidatas razoáveis).
        4. Para no teto MAX_K — nunca envia mais que isso.
        5. Se nenhuma tool passou o threshold, retorna a top-1 (safety net).

        Resultado: pode retornar 1, 2, 3... até MAX_K tools.
        NÃO força um mínimo artificial.
        """
        if not self._tools:
            return []

        if not self._available or not self._embeddings:
            return self._tools

        k = max_k or self.max_k
        always = always_include or _ALWAYS_INCLUDE

        scored = self._rank(user_text)

        selected_indices: list[int] = []
        for idx, score in scored:
            if len(selected_indices) >= k:
                break
            tool_name = self._tools[idx]["name"]
            if score >= self.min_score or tool_name in always:
                selected_indices.append(idx)

        if not selected_indices and scored:
            selected_indices.append(scored[0][0])

        if always:
            for i, t in enumerate(self._tools):
                if t["name"] in always and i not in selected_indices:
                    selected_indices.append(i)

        result = [self._tools[i] for i in selected_indices]

        self._log_selection(result, selected_indices, scored)
        return result

    def select_for_cycle(
        self,
        user_text: str,
        used_tool_names: set[str],
        max_k: int | None = None,
    ) -> list[dict]:
        """
        Seleção inteligente para ciclos de tool_use.

        Em vez de enviar TODAS as tools (10+) durante um ciclo — que era o maior
        desperdício de tokens — esta função:
        1. GARANTE as tools que a IA usou no turno anterior (ela precisa delas
           para processar os resultados e decidir os próximos passos).
        2. ADICIONA vizinhas relevantes por RAG, até o teto MAX_K.

        Isso reduz de ~10 tools por turno para ~3-5 no ciclo.

        Parâmetros
        ──────────
        user_text       : último texto real do usuário (para RAG).
        used_tool_names : nomes das tools usadas pela IA no turno anterior.
        max_k           : teto (padrão: MAX_K).
        """
        if not self._tools:
            return []

        if not self._available or not self._embeddings:
            return self._tools

        k = max_k or self.max_k

        guaranteed_indices: list[int] = []
        for name in used_tool_names:
            idx = self._tool_name_to_idx.get(name)
            if idx is not None:
                guaranteed_indices.append(idx)

        remaining = k - len(guaranteed_indices)
        selected_indices = list(guaranteed_indices)
        scored: list[tuple[int, float]] = self._rank(user_text) if self._available else []

        if remaining > 0:
            for idx, score in scored:
                if len(selected_indices) >= k:
                    break
                if idx in selected_indices:
                    continue
                if score >= self.min_score:
                    selected_indices.append(idx)

        result = [self._tools[i] for i in selected_indices]

        self._log_selection(result, selected_indices, scored, label="cycle")
        return result

    def _log_selection(
        self,
        result: list[dict],
        selected_indices: list[int],
        scored: list[tuple[int, float]],
        label: str = "RAG",
    ) -> None:
        """Log compacto da seleção."""
        scores_map = dict(scored)
        score_info = " | ".join(
            f"{t['name']}={scores_map.get(selected_indices[i], 0):.2f}"
            for i, t in enumerate(result)
        )
        print(f"[🔍 ToolRAG/{label}] {len(result)}/{len(self._tools)} tools → {score_info}")

    @property
    def is_available(self) -> bool:
        """True se sentence-transformers está instalado e o modelo carregado."""
        return self._available

    @property
    def tool_count(self) -> int:
        """Quantidade de tools atualmente indexadas."""
        return len(self._tools)
