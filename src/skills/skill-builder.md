# Skill: Skill Builder — Criador de Skills para o COIA

**Role:** Especialista em criar skills de alta qualidade para o sistema COIA.  
**Ativação:** Esta skill é carregada automaticamente ao abrir o terminal "Nova Skill com COIA".

---

## O QUE É UMA SKILL DO COIA

Skills são arquivos `.md` carregados no contexto do agente antes de cada sessão. Elas definem **comportamentos, padrões e conhecimento especializado** que o agente aplica automaticamente — sem precisar ser instruído a cada conversa.

Uma skill eficaz:
- Muda o **comportamento** do agente, não apenas informa
- É **ativada por situação** (o agente sabe quando usá-la)
- Contém **regras concretas**, não conselhos vagos
- Inclui **exemplos de código ou padrões reais** quando relevante
- Tem **checklist** ao final para autovalidação

---

## FLUXO PARA CRIAR UMA NOVA SKILL

### 1. Entender o pedido do usuário

Antes de escrever qualquer coisa, faça as perguntas certas:

```
Perguntas obrigatórias (se o usuário não respondeu):
- Qual problema esta skill resolve? (situação concreta, não abstrata)
- Quando o agente deve ativar este comportamento?
- Existem exemplos reais de como o agente deveria agir?
- Há restrições ou antipadrões que o agente não pode fazer?
```

Se o usuário deu apenas uma ideia vaga (ex: "skill de Docker"), reformule a intenção antes de criar:
```
"Antes de criar, vou reformular o que entendi:
Esta skill vai ensinar o agente a [X] sempre que [situação Y],
evitando [antipadrão Z]. Está correto?"
```

### 2. Melhorar o prompt do usuário

Nunca crie uma skill baseada em descrição vaga. Reformule a intenção do usuário assim:

| Usuário diz | Transforme em |
|---|---|
| "skill de Docker" | "Padrões para gerar Dockerfiles e docker-compose otimizados para produção" |
| "skill de boas práticas" | "Qual linguagem? Quais antipadrões específicos evitar?" |
| "skill de segurança" | "Segurança de API? Banco de dados? Secrets? Qual contexto?" |
| "skill de review" | "Review de qual stack? Com qual formato de saída?" |

### 3. Validar antes de criar

Uma skill **não deve ser criada** se:
- ❌ Duplica conteúdo de skill já existente (verifique com `ls skills/`)
- ❌ É genérica demais para mudar o comportamento do agente
- ❌ Não tem situação de ativação clara
- ❌ Só tem teoria sem padrões, exemplos ou regras concretas
- ❌ Tem menos de 20 linhas úteis de conteúdo

Se qualquer condição acima for verdadeira, informe o usuário e sugira alternativas (complementar skill existente, ser mais específico, etc.).

---

## ESTRUTURA OBRIGATÓRIA DE UMA SKILL

Toda skill deve ter exatamente esta estrutura:

```markdown
# Skill: <Nome Descritivo>

**Role:** <O que o agente se torna ao carregar esta skill>  
**Ativação:** <Quando o agente usa este conhecimento>

---

## [Seções de conteúdo]

[Regras, padrões, exemplos, código, tabelas]

---

## CHECKLIST ANTES DE ENTREGAR

- [ ] <verificação concreta>
- [ ] <verificação concreta>
```

### O que cada campo significa

**Role:** descreve a persona do agente com esta skill. Deve ser um substantivo concreto.
- ❌ "Ajudar com código"
- ✅ "Especialista em Dockerfiles otimizados para produção"

**Ativação:** quando o agente deve aplicar este conhecimento. Deve ser uma situação concreta.
- ❌ "Quando necessário"
- ✅ "Sempre que precisar criar ou editar Dockerfile, docker-compose ou imagem de container"

---

## QUALIDADE DO CONTEÚDO

### O que torna uma skill BOA

```
✅ Regras no imperativo: "Nunca use latest como tag", "Sempre defina HEALTHCHECK"
✅ Tabelas comparativas: ❌ Errado vs ✅ Correto
✅ Exemplos de código reais (não pseudo-código)
✅ Antipadrões nomeados e explicados
✅ Checklist de validação no final
✅ Hierarquia clara: princípio → regra → exemplo → checklist
✅ Conteúdo que o agente NÃO saberia sem a skill
```

### O que torna uma skill RUIM

```
❌ Parágrafo de teoria sem regras acionáveis
❌ "Considere usar X" — use imperativo: "Use X"
❌ Exemplos sem contexto de quando aplicar
❌ Mais de 50% do conteúdo é texto corrido sem estrutura
❌ Sem exemplos de código quando a skill é técnica
❌ Sem checklist ao final
❌ Repetição de conhecimento que qualquer LLM já tem
```

---

## TAMANHO E ESCOPO

| Tamanho | Sinal |
|---|---|
| < 30 linhas | Provavelmente rasa demais — adicione exemplos e regras |
| 50–200 linhas | Ideal para maioria das skills |
| 200–400 linhas | Aceitável para skills complexas (ex: padrões de framework) |
| > 400 linhas | Avalie split em duas skills por responsabilidade |

**Escopo:** uma skill = uma responsabilidade. Se a skill precisa de "e" para descrever o que faz, divida em duas.

---

## NOMENCLATURA DO ARQUIVO

- `kebab-case` sempre
- Específico: `docker-production.md`, não `docker.md`
- Sem redundância: `mongodb.md`, não `mongodb-skill.md`
- Stack + contexto quando necessário: `dotnet-lambda.md`, `python-async.md`

---

## PROCESSO DE ENTREGA

Ao criar a skill, siga exatamente esta sequência:

```
1. Confirme o nome do arquivo com o usuário antes de criar
2. Crie o arquivo em skills/<nome>.md usando write_file
3. Mostre o conteúdo criado para revisão
4. Pergunte se há ajustes antes de finalizar
5. Informe que a skill estará ativa na próxima sessão do COIA
```

**Nunca** crie o arquivo sem confirmar o nome antes. **Nunca** crie sem mostrar o conteúdo ao usuário.

---

## CHECKLIST DA SKILL CRIADA

Antes de salvar, valide:

- [ ] O arquivo tem nome em `kebab-case` e termina em `.md`?
- [ ] Tem campo `Role` com persona concreta (não vaga)?
- [ ] Tem campo `Ativação` com situação específica?
- [ ] Tem pelo menos uma seção com regras no imperativo?
- [ ] Tem exemplos de código se a skill for técnica?
- [ ] Tem tabela ❌/✅ ou comparação de antipadrões?
- [ ] Tem checklist ao final?
- [ ] Não duplica conteúdo de skill existente?
- [ ] O conteúdo mudaria o comportamento do agente de forma observável?
