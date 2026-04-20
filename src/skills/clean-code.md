# Skill: Clean Code

**Role:** Escrever código limpo, enxuto e autoexplicativo.  
**Ativação:** Sempre que for criar ou modificar código, independente da linguagem.

---

## Princípio central

> Código bom não precisa de comentário para ser entendido. Se precisar de comentário para explicar o que faz, reescreva até dispensar o comentário.

O nome certo no lugar certo vale mais que qualquer explicação em prosa.

---

## Comentários — regra de ouro

### ❌ Nunca comente o óbvio

```python
# Incrementa o contador
count += 1

# Retorna o usuário
return user

# Verifica se está ativo
if user.is_active:
```

```csharp
// Construtor
public DocumentService(IDocumentRepository repo) { ... }

// Salva o documento
await _repo.SaveAsync(doc);
```

Esses comentários não acrescentam nada — só aumentam ruído e tokens.

### ❌ Nunca comente a assinatura do método

```python
# Busca usuário por ID
# Parâmetros: id (int)
# Retorna: User
def get_user(id: int) -> User:
```

A assinatura já diz tudo. Comentário duplica sem agregar.

### ✅ Comente apenas o porquê — nunca o quê

O único comentário válido é aquele que explica uma **decisão não óbvia**, uma **restrição externa** ou um **comportamento contraintuitivo** que o código em si não consegue expressar.

```python
# Firestore não suporta arrays vazios — envia None para evitar erro de serialização
payload["tags"] = tags or None
```

```csharp
// Timeout reduzido para 2s: SLA do parceiro exige resposta em menos de 3s
_client.Timeout = TimeSpan.FromSeconds(2);
```

```typescript
// CDKTF exige que o bucket seja criado antes do IAM binding — dependência implícita
bucket.node.addDependency(serviceAccount);
```

Se o comentário começa com "isso faz X" → delete.  
Se começa com "isso é assim porque Y" → pode ficar, se Y não for óbvio.

### Proporção esperada

Em um arquivo bem escrito: **zero comentários** é o padrão. Um ou dois em um arquivo inteiro é aceitável. Mais que isso é sinal de que o código precisa ser refatorado, não explicado.

---

## Nomes — a principal ferramenta do clean code

Um nome bom elimina a necessidade de qualquer comentário.

### Seja específico, não genérico

| ❌ Vago | ✅ Específico |
|---|---|
| `data` | `invoicePayload` |
| `result` | `createdDocument` |
| `process()` | `convertPdfToText()` |
| `handle()` | `handleWebhookTimeout()` |
| `flag` | `isEmailVerified` |
| `temp` | `rawResponseBody` |
| `info` | `userProfileSnapshot` |
| `manager` | `DocumentUploadCoordinator` |

### Booleanos — sempre afirmação positiva

```python
# ❌
if not disabled:
if no_error:

# ✅
if is_active:
if succeeded:
```

### Funções — verbo + objeto

```
# ❌
document()
userData()
processing()

# ✅
fetchDocumentById()
buildUserProfile()
processIncomingWebhook()
```

### Evite encodings e prefixos desnecessários

```csharp
// ❌ — prefixo I em interface já é obrigação da convenção, não informação extra
IDocumentRepositoryInterface
strUserName
intCount
bIsActive

// ✅
IDocumentRepository
userName
count
isActive
```

---

## Funções

### Faça uma coisa só

Se a função tem "e" no nome ou na descrição mental que você faria dela, ela está fazendo coisas demais.

```python
# ❌ — valida E salva E notifica
def save_and_notify_user(user):
    validate(user)
    db.save(user)
    email.send(user)

# ✅ — cada responsabilidade isolada
def save_user(user):
    validate_user(user)
    _repo.save(user)

def notify_user_created(user):
    _email.send_welcome(user)
```

### Tamanho ideal

- Função que cabe na tela sem scroll: boa.
- Função com mais de 30 linhas: candidata à extração.
- Função com mais de 50 linhas: extração obrigatória.

### Parâmetros — menos é mais

```python
# ❌ — 6 parâmetros posicionais = armadilha de ordem
def create_user(name, email, age, role, active, verified):

# ✅ — objeto agrupa e nomeia
def create_user(data: CreateUserRequest):
```

Mais de 3 parâmetros posicionais: agrupe em um objeto/dataclass/record.

### Sem flags booleanas como parâmetro de controle de fluxo

```python
# ❌ — o que significa True aqui?
render_report(data, True)

# ✅ — duas funções com intenção clara
render_report_as_pdf(data)
render_report_as_html(data)
```

---

## Estrutura e fluxo

### Retorne cedo — evite else desnecessário

```python
# ❌ — aninhamento desnecessário
def process(doc):
    if doc is not None:
        if doc.is_valid():
            return save(doc)
        else:
            raise ValueError("inválido")
    else:
        raise ValueError("nulo")

# ✅ — guard clauses
def process(doc):
    if doc is None:
        raise ValueError("nulo")
    if not doc.is_valid():
        raise ValueError("inválido")
    return save(doc)
```

### Não anuncie o que vai fazer — faça

```python
# ❌
# Itera sobre os documentos e processa cada um
for doc in documents:
    process(doc)

# ✅ — o código já diz isso
for doc in documents:
    process(doc)
```

### Evite negações duplas

```python
# ❌
if not is_not_valid:

# ✅
if is_valid:
```

---

## Código morto — delete sem cerimônia

Nunca deixe no código:

- Métodos comentados aguardando "talvez usar depois"
- Variáveis declaradas e nunca lidas
- Imports não utilizados
- Branches `if False:` ou condições impossíveis
- `TODO` sem data e sem dono (se não tem issue, não tem prazo — delete ou crie a issue)

```python
# ❌
# def old_process(doc):
#     ...antiga implementação...

# ❌
import os  # não usado

# ❌
# TODO: refatorar isso
x = x * 1
```

O controle de versão guarda o histórico. Código comentado no repositório é lixo com data de validade vencida.

---

## Tamanho de arquivo

| Tamanho | Sinal |
|---|---|
| < 200 linhas | Saudável |
| 200–400 linhas | Aceitável, monitorar |
| > 400 linhas | Candidato a split por responsabilidade |
| > 600 linhas | Split obrigatório |

Arquivo grande quase sempre significa mais de uma responsabilidade no mesmo lugar.

---

## Consistência é lei

Dentro de um projeto, escolha uma convenção e siga sem exceções:

- Nomenclatura: `camelCase` para JS/TS/JSON, `PascalCase` para C#/tipos, `snake_case` para Python
- Organização de imports: stdlib → third-party → interno
- Ordem dos membros da classe: constantes → campos → construtor → métodos públicos → métodos privados

Inconsistência força o leitor a decifrar padrões em vez de ler o código.

---

## Checklist antes de commitar

- [ ] Todo nome de variável, função e classe é autoexplicativo sem precisar de comentário?
- [ ] Algum comentário explica o **quê** em vez do **porquê**? Se sim, delete.
- [ ] Existe código comentado ou imports não utilizados? Delete.
- [ ] Alguma função faz mais de uma coisa? Extraia.
- [ ] Alguma função tem mais de 3 parâmetros posicionais? Agrupe.
- [ ] Existe `else` que poderia ser eliminado com guard clause? Elimine.
- [ ] O arquivo tem mais de 400 linhas? Avalie split.
