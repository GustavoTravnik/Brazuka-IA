# COIA — AI CLI Assistant

## O que é o COIA?

**COIA** (Custom Open Intelligence Assistant) é um agente de IA customizado desenvolvido internamente, que roda diretamente no terminal e serve como assistente técnico inteligente para o dia a dia do time de desenvolvimento.

Ele é construído sobre o modelo **Claude (via Anthropic Vertex AI no GCP)** e foi projetado para ser extensível, contextual e altamente configurável — podendo atuar tanto como um chatbot interativo quanto como uma **equipe de agentes especializados (Crew Mode)** trabalhando em conjunto para resolver tarefas complexas.

---

## Primeiros passos — setup inicial

Se você acabou de clonar o repositório, siga estes passos:

### 1. Rode o setup

```bash
chmod +x setup.sh
./setup.sh
```

O script vai:
- Verificar (e instalar, se necessário) o Python3
- Criar o ambiente virtual `.venv`
- Instalar todas as dependências de `src/requirements.txt`
- Copiar `src/.env.dev` → `src/.env` para você configurar
- Perguntar se deseja adicionar os aliases `coia` e `coia-web` ao `~/.bashrc`

### 2. Configure o `.env`

Edite o arquivo `src/.env` com suas credenciais e configurações:

```bash
nano src/.env
```

> Consulte os tokens e configurações necessárias em:
> - https://dev-portal.open-co.com/
> - https://dev-portal.open-co.com/setup

### 3. Recarregue o terminal

Se adicionou os aliases durante o setup:

```bash
source ~/.bashrc
```

### 4. Use

```bash
coia        # abre o assistente no terminal
coia-web    # abre a interface web
```

---

## Arquitetura do `src/`

```
src/
├── app.py                      # Entrypoint principal — loop de chat no terminal
├── models/
│   └── agent.py                # Modelo de dados de um agente (persona, roles, skills, tools)
├── controllers/
│   ├── agent_orchestrator.py   # Carrega e orquestra uma crew a partir de um YAML
│   ├── command_manager.py      # Gerencia comandos de atalho (/comando)
│   ├── mcp_manager.py          # Gerencia servidores MCP externos (Jira, Bitbucket, AWS, Slack)
│   ├── native_tools.py         # Ferramentas nativas: read_files, shell_execute, write_file
│   └── skill_manager.py        # Carrega skills técnicas (.md) no system prompt
├── services/
│   ├── crew.py                 # Motor de execução da equipe de agentes com loop de ferramentas
│   └── semantic_router.py      # Roteador semântico que decide qual agente age em seguida
├── mcp-servers/                # Servidores MCP registrados (aws.py, jira.py, bitbucket.py, slack.py)
├── skills/                     # Skills técnicas em Markdown injetadas no contexto do agente
├── commands/                   # Comandos de atalho (/issue, /analyse, etc.) em Markdown
├── prompts/                    # Prompts reutilizáveis executados via #prompt
├── crews/                      # Configurações YAML de equipes de agentes
└── panel/                      # Interface web (Flask) para interação alternativa ao terminal
```

---

## Principais Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| **Chat interativo** | Loop de conversa com Claude no terminal, com histórico persistente |
| **AGENT.md contextual** | Se existir um `agent.md` na raiz do projeto, o COIA carrega o contexto do projeto automaticamente |
| **Skills dinâmicas** | Skills técnicas (`.md`) são injetadas no system prompt via `@Useful-Skills` ou `--skills` |
| **Ferramentas nativas** | `read_files`, `shell_execute` e `write_file` executados localmente |
| **Servidores MCP** | Integração com Jira, Bitbucket, AWS e Slack via protocolo MCP |
| **Crew Mode** | Equipes de agentes configuradas em YAML que colaboram e se roteiam semanticamente |
| **Commands** | Atalhos de prompt via `/comando` que injetam Markdowns pré-definidos |
| **Prompt Files** | Execução de prompts reutilizáveis via `#prompt <nome>` |
| **Controle de custo** | Exibe tokens consumidos, cache hit e custo em R$ a cada resposta |
| **Interface Web** | Painel web via Flask como alternativa ao terminal |

---

## Como funciona o Crew Mode?

O **Crew Mode** permite definir times de agentes em arquivos `.yaml` na pasta `crews/`. Cada agente tem:
- **Persona e roles** — quem ele é e o que faz
- **Skills** — habilidades técnicas específicas a serem carregadas
- **Tools** — quais ferramentas (nativas ou MCP) ele pode usar
- **Transitions** — condições semânticas que definem qual agente age em seguida

O **SemanticRouter** usa um modelo leve (Gemini 1.5 Flash) para analisar a saída de cada agente e decidir o próximo passo do fluxo automaticamente.

```bash
# Exemplo de uso do Crew Mode
#crew jira-task-resolver "Resolver a issue PROJ-123 e abrir PR no Bitbucket"
```

---

## Stack Técnica

- **LLM:** Claude Sonnet/Haiku via [Anthropic Vertex AI](https://cloud.google.com/vertex-ai)
- **Linguagem:** Python 3.10+
- **Protocolo de ferramentas:** [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
- **Integrações:** Jira, Bitbucket, AWS, Slack
- **Interface:** Terminal (`prompt_toolkit`) + Web (`Flask`)
- **Infraestrutura:** GCP (Vertex AI)

---

## Gerar token e setup do agente do Claude:
   - https://dev-portal.open-co.com/
   - https://dev-portal.open-co.com/setup

## Alias

Os wrappers `src/coia.sh` e `src/coia-web.sh` já resolvem o venv automaticamente — **não é necessário `source .venv/bin/activate` antes de usar**.

Adicione ao seu `~/.bashrc` (ajuste o caminho para onde você clonou o projeto):

```bash
alias coia="/caminho/para/coia/src/coia.sh"
alias coia-web="/caminho/para/coia/src/coia-web.sh"
```

Depois recarregue:

```bash
source ~/.bashrc
```

## Instalação de skills/MCPs

### Required to all
   - npm and npx:
      - sudo apt update && sudo apt upgrade -y
      - curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
      - sudo apt-get install -y nodejs

### AWS
   - curl -LsSf https://astral.sh/uv/install.sh | sh

### RTK
   - curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
   - rtk init --global *configuração para adicionar o RTK no claude code e definir no padrão CLAUDE.md*

## Instalar o venv do python + requirements
   - cd src
   - python3 -m venv .venv
   - source .venv/bin/activate
   - pip3 install -r requirements.txt

## Troubles:
   - As credenciais do gcloud provavelmente expiraram desde ontem. Para resolver, rode:
      ! gcloud auth login
      ou
      ! gcloud auth application-default login
      Depois de autenticar, tente rodar a IA novamente.

**TODO**
   - Executar a sprint usando o console do COIA na interface web
   - Adicionar parametros de criação da sprint como importar do jira por exemplo
   - Terraform, 
   - cdk
   - terraform com cdk   
rraform, 
   - cdk
   - terraform com cdk   
