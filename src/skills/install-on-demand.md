# Skill: Install on Demand

**Role:** Agente que detecta dependências ausentes e conduz a instalação de forma interativa antes de prosseguir com qualquer tarefa.  
**Ativação:** Sempre que uma ferramenta, CLI, binário, pacote ou dependência necessária para executar uma ação não estiver disponível no ambiente.

---

## PRINCÍPIO CENTRAL

> Nunca falhe silenciosamente por falta de dependência. Detecte, informe e ofereça instalar — antes de tentar executar.

O agente nunca deve assumir que uma ferramenta está disponível sem verificar. Se não estiver, conduz o usuário pelo processo de instalação.

---

## 1. FLUXO OBRIGATÓRIO

```
1. Detectar → verificar se a ferramenta/dependência existe no ambiente
2. Informar  → comunicar o que está faltando e por que é necessário
3. Oferecer  → perguntar se o usuário quer instalar agora
4. Coletar   → pedir informações necessárias para instalação (se houver)
5. Instalar  → executar o comando de instalação com confirmação
6. Validar   → confirmar que a instalação funcionou antes de prosseguir
```

Nunca pule etapas. Nunca execute instalação sem confirmação explícita do usuário.

---

## 2. DETECÇÃO — SEMPRE VERIFIQUE ANTES DE USAR

| Tipo | Comando de verificação |
|---|---|
| Binário/CLI genérico | `which <cmd>` ou `command -v <cmd>` |
| Python package | `pip show <pacote>` ou `python -c "import <pacote>"` |
| Node package global | `npm list -g <pacote>` ou `npx <cmd> --version` |
| .NET tool global | `dotnet tool list -g` |
| Docker | `docker info` |
| RTK | `which rtk` |
| uvx (MCP Python runner) | `which uvx` ou `uvx --version` |
| npx (MCP Node runner) | `which npx` ou `npx --version` |

```bash
# ✅ Sempre detecte antes de usar
command -v jq >/dev/null 2>&1 || echo "AUSENTE"

# ❌ Nunca execute direto sem checar
jq '.field' arquivo.json
```

---

## 3. COMUNICAÇÃO — COMO INFORMAR O USUÁRIO

Ao detectar dependência ausente, comunique com clareza:

```
❌ Vago:
"Não foi possível executar o comando."

✅ Correto:
"Para [objetivo], preciso do `jq` — utilitário de parsing de JSON.
Ele não está instalado no seu ambiente.
Posso instalar agora? (brew install jq / apt install jq)"
```

Estrutura obrigatória da mensagem:
1. **O que está faltando** — nome exato da ferramenta
2. **Por que é necessária** — qual tarefa depende dela
3. **Oferta de instalação** — pergunta direta: "Posso instalar agora?"
4. **Comando que será executado** — mostre antes de rodar

---

## 4. COLETA DE INFORMAÇÕES — QUANDO PERGUNTAR

Algumas instalações exigem informações do usuário antes de prosseguir:

| Situação | O que perguntar |
|---|---|
| Versão específica necessária | "Qual versão prefere? (padrão: latest)" |
| Path de instalação customizado | "Onde deseja instalar? (padrão: ~/.local/bin)" |
| Token ou credencial necessária | "Você tem o token de acesso para [serviço]?" |
| Escolha de método de instalação | "Prefere instalar via brew, apt ou manualmente?" |
| Permissão de sudo | "Esta instalação requer sudo. Você tem permissão?" |

Pergunte **somente o que for necessário**. Não faça perguntas desnecessárias se o padrão é suficiente.

---

## 5. COMANDOS DE INSTALAÇÃO — REFERÊNCIA POR FERRAMENTA

### RTK
```bash
# Verificação
which rtk

# Instalação (Linux/macOS)
curl -sSL https://get.rtk.sh | bash
```

### uvx (runner de MCPs Python)
```bash
# Verificação
which uvx

# Instalação via pip
pip install uv

# Ou via curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### npx (runner de MCPs Node)
```bash
# Verificação
which npx

# npx vem com Node.js — instalar Node resolve
# macOS
brew install node

# Linux
apt install nodejs npm
```

### Dependências de MCPs Python (via uvx)
```bash
# uvx instala automaticamente o pacote ao rodar
uvx <nome-do-pacote> [args]

# Se instalação persistente for necessária
uv tool install <nome-do-pacote>
```

### Dependências de MCPs Node (via npx)
```bash
# npx baixa e executa sem instalar globalmente
npx <nome-do-pacote> [args]

# Se instalação global for necessária
npm install -g <nome-do-pacote>
```

### CLIs comuns
```bash
# jq
brew install jq           # macOS
apt install jq            # Debian/Ubuntu

# gh (GitHub CLI)
brew install gh           # macOS
apt install gh            # Debian/Ubuntu

# glab (GitLab CLI)
brew install glab         # macOS
apt install glab          # Debian/Ubuntu

# docker
brew install --cask docker  # macOS
apt install docker.io       # Debian/Ubuntu

# .NET tool global
dotnet tool install -g <nome>

# Python package
pip install <nome>

# Node package global
npm install -g <nome>
```

---

## 6. VALIDAÇÃO PÓS-INSTALAÇÃO

Após instalar, sempre valide antes de prosseguir:

```bash
# ✅ Confirme que funciona
<ferramenta> --version

# ✅ Para PATH: recarregue se necessário
source ~/.bashrc  # ou ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

Se a validação falhar:
1. Mostre o erro completo
2. Sugira diagnóstico (PATH, permissão, dependência transitiva)
3. Não prossiga com a tarefa original até resolver

---

## 7. ANTIPADRÕES — NUNCA FAÇA

```
❌ Executar ferramenta sem checar se existe
❌ Instalar sem mostrar o comando ao usuário antes
❌ Instalar sem confirmação explícita ("Posso instalar?" → esperar resposta)
❌ Assumir que sudo está disponível sem perguntar
❌ Instalar versão diferente da necessária sem avisar
❌ Ignorar falha de validação pós-instalação e prosseguir mesmo assim
❌ Pedir informações desnecessárias quando o padrão resolve
```

---

## 8. EXEMPLO COMPLETO — FLUXO IDEAL

**Situação:** usuário pede para rodar um MCP que depende de `uvx`, que não está instalado.

```
Agente detecta: `which uvx` → não encontrado

Agente comunica:
"Para executar este MCP, preciso do `uvx` — runner de pacotes Python da Astral.
Ele não está instalado no seu ambiente.

Posso instalar agora rodando:
  curl -LsSf https://astral.sh/uv/install.sh | sh

Deseja prosseguir?"

Usuário: "sim"

Agente executa: curl -LsSf https://astral.sh/uv/install.sh | sh
Agente valida:  uvx --version → OK

Agente: "✅ uvx instalado com sucesso (versão X.Y.Z). Prosseguindo com o MCP..."
```

---

## CHECKLIST ANTES DE USAR QUALQUER FERRAMENTA

- [ ] Verifiquei se a ferramenta está disponível com `which` ou equivalente?
- [ ] Se ausente: informei o usuário com nome, motivo e comando de instalação?
- [ ] Pedi confirmação antes de executar a instalação?
- [ ] Coletei informações necessárias (versão, path, credencial) quando relevante?
- [ ] Validei que a instalação funcionou antes de prosseguir?
- [ ] Se a validação falhou: investiguei e não prossegui com a tarefa original?
