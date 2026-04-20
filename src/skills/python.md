# Skill: Python Developer

**Role:** Escrever e revisar código Python idiomático, performático e seguro.  
**Ativação:** Sempre que precisar gerar ou revisar código Python.

---

## 1. PRINCÍPIOS

- **Pythonic first:** list comprehensions, generators, unpacking — nunca loops verbose onde a linguagem oferece alternativa
- **Explícito > implícito:** nomes autodescritivos, sem abreviações obscuras
- **Uma responsabilidade por função:** se precisar de "e" para descrever o que faz, separe em duas
- **Fail fast:** valide entradas no início da função com exceções específicas
- **Não repita código:** extraia lógica repetida — mas não crie abstração para uso único

---

## 2. NOMENCLATURA E ESTILO (PEP 8)

| Elemento | Padrão |
|---|---|
| Funções e variáveis | `snake_case` |
| Classes | `PascalCase` |
| Constantes de módulo | `UPPER_SNAKE_CASE` |
| Parâmetros internos | `_prefixo` |
| Módulos e pacotes | `snake_case` (sem hifens) |

- Indentação: **4 espaços**, nunca tabs
- Linha máxima: **88 chars** (padrão black/ruff)
- Duas linhas em branco entre definições de nível superior
- Uma linha em branco entre métodos de classe

---

## 3. TYPE HINTS (OBRIGATÓRIO)

```python
def process(items: list[str], limit: int = 10) -> dict[str, int]:
    ...
```

- Use `X | None` (Python 3.10+) ou `Optional[X]` para valores opcionais
- Use `TypedDict` para dicts com estrutura conhecida
- Use `Protocol` para duck typing explícito
- **Nunca** deixe `mypy` passar com `# type: ignore` sem comentário explicando

---

## 4. IMPORTS

```python
# 1. stdlib
import os
from pathlib import Path

# 2. third-party
import httpx
from pydantic import BaseModel

# 3. local
from .utils import parse_response
```

- **Nunca** `from modulo import *`
- **Nunca** import dentro de função sem motivo explícito
- Prefira imports absolutos

---

## 5. TRATAMENTO DE ERROS

```python
# Sempre capturar exceção específica
try:
    result = fetch_data(url)
except httpx.TimeoutException as e:
    logger.error("Timeout ao buscar %s: %s", url, e)
    raise

# Exceções de domínio
class UserNotFoundError(ValueError):
    def __init__(self, user_id: int) -> None:
        super().__init__(f"Usuário {user_id} não encontrado.")
```

- **Nunca** `except: pass` ou `except Exception: pass`
- **Nunca** `except Exception as e: print(e)` sem re-raise
- Use `contextlib.suppress` apenas quando o silêncio for intencional e documentado
- Valide entradas com `raise ValueError(...)` no início da função

---

## 6. PADRÕES DE PERFORMANCE

| Situação | ❌ Evitar | ✅ Usar |
|---|---|---|
| Strings em loop | `s += item` | `"".join(items)` |
| Busca em coleção dentro de loop | `item in lista` (O(n)) | `item in set(lista)` (O(1)) |
| Iterar com índice | `for i in range(len(x))` | `for i, v in enumerate(x)` |
| Arquivo grande | `f.read()` inteiro | `for line in f:` |
| Lista só para iterar | `[x for x in ...]` | `(x for x in ...)` (generator) |
| Verificar tipo | `type(x) == int` | `isinstance(x, int)` |
| Comparar com None | `x == None` | `x is None` |

- Use `pathlib.Path` em vez de `os.path`
- Use `__slots__` em classes com muitas instâncias
- Prefira `logging` a `print()` em produção

---

## 7. ASYNC (quando aplicável)

```python
# ✅ Operações de I/O concorrentes
results = await asyncio.gather(fetch(url_a), fetch(url_b))

# ❌ Bloqueante dentro de coroutine
async def handler():
    time.sleep(1)       # trava o event loop
    data = file.read()  # use aiofiles
```

- **Nunca** `time.sleep` dentro de coroutine — use `await asyncio.sleep`
- Sempre `await` com `try/except`
- Tasks criadas com `asyncio.create_task` devem ter referência mantida

---

## 8. SEGURANÇA — NUNCA FAZER

- `eval()` ou `exec()` com qualquer dado externo
- `subprocess` com `shell=True` e input do usuário
- Query SQL via f-string — use parâmetros do driver (`%s`, `?`)
- `pickle.loads()` com dado não confiável
- Secrets hardcoded — use variáveis de ambiente
- `yaml.load()` sem `Loader=yaml.SafeLoader`
- Argumento padrão mutável: `def f(lst=[])` — use `def f(lst=None)`

---

## 9. LINT E FERRAMENTAS

```bash
ruff check .
ruff format --check .
mypy src/
```

**Nomenclatura (PEP 8):**
- [ ] Funções e variáveis: `snake_case`
- [ ] Classes: `PascalCase`
- [ ] Constantes: `UPPER_SNAKE_CASE`

**Imports:**
- [ ] 3 blocos: stdlib → third-party → local, separados por linha em branco
- [ ] Sem `import *`
- [ ] Imports absolutos preferidos

---

## 10. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

### Erros Silenciosos
- [ ] `except:` ou `except Exception: pass`
- [ ] `except Exception as e:` sem re-raise ou log
- [ ] `try/except` cobrindo bloco grande demais

### Armadilhas da Linguagem
- [ ] Argumento padrão mutável: `def f(lst=[])`
- [ ] `is` para comparar valores (`x is 1`) — use `==`
- [ ] `== None` — use `is None`
- [ ] Modificação de lista durante iteração
- [ ] `except BaseException` — captura `KeyboardInterrupt`

### Performance
- [ ] Concatenação de string em loop: `s += x`
- [ ] `item in lista` em loop — use `set`
- [ ] `for i in range(len(lst))` — use `enumerate`
- [ ] `.read()` em arquivo grande
- [ ] List comprehension gerando lista só para iterar — use generator

### Qualidade
- [ ] Função sem type hints
- [ ] Variável nomeada `l`, `O`, `I` — confundível com `1` e `0`
- [ ] `print()` em produção onde `logging` deveria ser usado
- [ ] Números mágicos sem constante nomeada

### Segurança
- [ ] `eval()` ou `exec()` com input externo
- [ ] `subprocess` com `shell=True` e input
- [ ] Query SQL via f-string
- [ ] `pickle.loads()` com dado não confiável
- [ ] `yaml.load()` sem `SafeLoader`

### Async
- [ ] `time.sleep` dentro de coroutine
- [ ] Task criada sem `await` e sem referência — coletada pelo GC

### Imports
- [ ] Import circular
- [ ] `from modulo import *`
- [ ] Dependência não declarada no `pyproject.toml`

---

## 11. FORMATO DE SAÍDA PARA CODE REVIEW

```
## Code Review — Python

### Problemas encontrados

| # | Arquivo/Trecho | Severidade | Problema | Correção sugerida |
|---|---|---|---|---|
| 1 | `service.py:88` | CRÍTICO | `eval()` com input do usuário | Remover eval, usar parsing seguro |
| 2 | `utils.py:12` | CRÍTICO | `except: pass` engole todas as exceções | Capturar exceção específica e logar |

### Prompt de correções

Corrija os seguintes problemas no código Python:

1. [CRÍTICO] Em `<arquivo>:<linha>`: <descrição e como corrigir>
2. [MAIOR] Em `<arquivo>:<linha>`: <descrição e como corrigir>

Priorize os itens CRÍTICOS. Mantenha o estilo e convenções existentes.
```

**Severidades:**
- **CRÍTICO:** exceção silenciosa, falha de segurança, corrupção de estado
- **MAIOR:** degradação de performance, antipadrão que compromete manutenção
- **MENOR:** convenção, type hints ausentes, legibilidade

---

## 12. CHECKLIST ANTES DE ENTREGAR

- [ ] Todas as funções têm type hints?
- [ ] `mypy` passa sem erros?
- [ ] `ruff check .` sem warnings?
- [ ] Nenhum `except: pass` ou genérico?
- [ ] Nenhum argumento padrão mutável?
- [ ] Sem `print()` em produção?
- [ ] Sem secrets hardcoded?
- [ ] Imports organizados e sem `import *`?
- [ ] Strings em loop usam `join`?
- [ ] Buscas em loop usam `set`?
