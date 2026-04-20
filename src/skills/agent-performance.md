# Skill: Agent Performance

**Role:** Agente eficiente no uso das ferramentas disponíveis, git e recursos de sistema.  
**Objetivo:** Minimizar tool calls, reduzir tokens consumidos e evitar trabalho redundante.

---

## 1. HIERARQUIA DE FERRAMENTAS — LEITURA E BUSCA

Ferramentas nativas são **sempre preferíveis ao shell** para leitura e busca:

| Operação | ❌ Evitar | ✅ Preferir | Motivo |
|---|---|---|---|
| Ler arquivos | `shell_execute: cat arquivo` | `read_files` | Sem subprocesso, batch nativo |
| Ler múltiplos arquivos | N chamadas separadas | `read_files` com lista | Uma chamada só |
| Explorar estrutura | `shell_execute: ls -la` ou `find` | `list_dir` | Retorno estruturado, por profundidade |
| Buscar padrão em código | `shell_execute: grep -r` | `search_text` | Grep Python nativo, sem subprocesso |
| Editar trecho pontual | `write_file` com arquivo inteiro | `patch_file` | Reescreve apenas o bloco alterado |
| Escrever arquivo novo | `shell_execute: echo ... > arquivo` | `write_file` | Sem risco de escaping de shell |

`shell_execute` deve ser reservado para: compilar, executar testes, comandos git, CLIs externas.

---

## 2. READ_FILES — LEITURA EM BATCH

Nunca leia arquivos um por um quando precisar de mais de um:

```
# ❌ Três chamadas
read_files: ["arquivo1.cs"]
read_files: ["arquivo2.cs"]
read_files: ["arquivo3.cs"]

# ✅ Uma chamada
read_files: ["arquivo1.cs", "arquivo2.cs", "arquivo3.cs"]
```

**Não releia o que já está no contexto.** Se o conteúdo foi retornado nesta sessão, use o que existe.

---

## 3. PATCH_FILE vs WRITE_FILE

- **`patch_file`**: arquivo existente, alteração pontual. Mais barato — não retransmite o arquivo inteiro.
- **`write_file`**: arquivo novo, ou 3+ alterações espalhadas (reescrever inteiro é mais eficiente que N patches).

```
# ❌ Reescrever arquivo inteiro para mudar 2 linhas
write_file: path="Program.cs", content="...arquivo inteiro..."

# ✅ Edição cirúrgica
patch_file: path="Program.cs", search_text="var old = ...", replace_text="var new = ..."
```

---

## 4. SHELL_EXECUTE — QUANDO E COMO USAR

### Encadeamento com dependência
```bash
# Só executa o próximo se o anterior passou
dotnet restore && dotnet build && dotnet test
```

### Filtrar na origem — nunca traga output desnecessário
```bash
# ❌
dotnet build 2>&1

# ✅
dotnet build 2>&1 | grep -E "error|warning" | head -30

# ❌ Log inteiro no contexto
cat app.log

# ✅
grep "ERROR" app.log | tail -20
```

### Limitar output de comandos longos
```bash
find . -name "*.cs" | head -30
psql -c "SELECT * FROM tabela LIMIT 20"
journalctl -u servico --since "1 hour ago" | tail -50
```

### CLI local > chamada de rede

| Situação | ❌ Evitar | ✅ Preferir |
|---|---|---|
| Último commit | `curl api.github.com/...` | `git rev-parse HEAD` |
| Info do repo | API REST do GitHub/Bitbucket | `git log / git show` |
| Parse de JSON | Script Python ad-hoc | `jq` |
| Busca em arquivo | `cat f \| grep p` | `search_text` ou `grep p f` |

---

## 5. GIT — USO EFICIENTE

### Prioridade de ferramentas para plataformas remotas
1. **Git CLI local** — `git log`, `git show`, `git rev-parse`, `git fetch`
2. **Platform CLIs** — `gh`, `glab` quando o git nativo for insuficiente
3. **curl / API HTTP** — último recurso, apenas para metadados que CLIs não expõem

### Interação com remotos
```bash
git remote -v                    # identificar plataforma e URL
git ls-remote <url>              # testar conexão sem clonar
git fetch --all --prune          # atualizar refs sem alterar working tree
git clone --depth 1 <url>        # clone rápido para leitura/auditoria
```

### Exploração local (mais rápido que chamadas remotas)
```bash
git ls-tree -r --name-only HEAD  # listar arquivos rastreados
git grep -n "termo"              # busca em conteúdo (usa índice git)
git log -p -- <arquivo>          # histórico de arquivo com diff
git diff --stat branch_a..branch_b  # comparação entre branches
```

### Reduzir output antes de trazer ao contexto
```bash
git log --oneline -10
git log --author="nome" --since="1 week ago" --oneline
git diff --shortstat
git show --stat HEAD
```

### Operações destrutivas — sempre verificar antes
```bash
git status && git diff --shortstat
```

Comandos que alteram histórico (`reset --hard`, `clean -fd`, `push --force`) exigem confirmação explícita do usuário antes de executar.

---

## 6. RTK (RUST TOKEN KILLER)

O RTK opera via hook do Claude Code — **todos os comandos de terminal já são prefixados automaticamente**. Não adicione `rtk` manualmente — causaria duplo prefixo (`rtk rtk git status`).

**Comandos que devem ser chamados explicitamente (não interceptados pelo hook):**
```bash
rtk gain              # Mostra economia de tokens acumulada na sessão
rtk gain --history    # Histórico de comandos e economia por chamada
rtk discover          # Analisa histórico e sugere oportunidades perdidas de usar RTK
rtk proxy <cmd>       # Executa sem filtragem (debug)
```

Use `rtk gain` ao final de sessões longas para reportar economia ao usuário.

---

## 7. CHECKLIST DE DECISÃO

Antes de cada tool call:

1. **Vou ler um arquivo?** → `read_files`, não `shell_execute: cat`
2. **Vou ler vários?** → `read_files` com lista, uma chamada só
3. **Vou explorar estrutura?** → `list_dir`, não `find` ou `ls`
4. **Vou buscar padrão?** → `search_text`, não `grep` via shell
5. **Vou alterar trecho pequeno de arquivo existente?** → `patch_file`, não `write_file` inteiro
6. **O resultado já está no contexto?** → Não execute. Use o que existe.
7. **Preciso de info de repositório remoto?** → `git log/show/rev-parse` antes de chamar API

---

## 8. REGRA CRÍTICA — NUNCA CHAME TOOLS COM INPUT VAZIO

```
# ❌ JAMAIS
shell_execute({})
write_file({})
read_files({})

# ✅ Só chame quando o parâmetro estiver 100% definido
shell_execute(command="git status")
write_file(path="/caminho/arquivo.py", content="conteúdo completo aqui")
read_files(paths=["arquivo1.py", "arquivo2.py"])
```

Se ainda está "pensando" no valor de um parâmetro obrigatório, continue o raciocínio em texto e só chame a tool quando todos os campos estiverem prontos. Isso se aplica especialmente a `write_file` — nunca chame sem o `content` completo.
