# coletor-arp

Baixa os arquivos anuais de atas de registro de preços (ARP) publicados pelo
Compras.gov.br no repositório de dados abertos da SEGES e os salva exatamente
como foram recebidos. O conteúdo não é descompactado, filtrado nem reescrito:
tratamento, recortes (como o dos medicamentos) e cruzamentos ficam no
repositório `medicamentos-fdcc`.

Criado a partir do [python-template-tb](https://github.com/Transparencia-Brasil/python-template-tb).

## Fonte e abrangência

- Repositório: <https://repositorio.dados.gov.br/seges/comprasgov/arp/>, com o
  `LEIAME.md` da própria fonte.
- Cada ano tem uma pasta com dois arquivos:
  - `atas_{ano}.csv.zip`: dados gerais das atas (número, unidade gerenciadora,
    compra de origem, datas de assinatura e vigência, valor total, links do PNCP);
  - `atas_itens_{ano}.csv.zip`: os itens de cada ata.

Pontos verificados na fonte em 23/11/2026:

- **Só há arquivos anuais**, de 2023 a 2026. Não existem pastas mensais ou
  diárias, como no repositório de contratos. Um ano não publicado responde 404.
- **O ano é o da ata, não o da assinatura.** Segundo o `LEIAME.md`, os arquivos
  são separados pelos quatro últimos caracteres de `numero_ata_registro_preco`
  (como `00204/2025`).
- **Os arquivos são republicados.** O do ano corrente é refeito toda semana, aos
  sábados às 8h, e anos anteriores podem ser substituídos quando há correção na
  fonte. O `Last-Modified` de cada arquivo aparece no log e indica a versão dos
  dados. Em 23/11/2026, os de 2025 eram de 10/10/2026.
- **Tamanho em 2025:** 14 MB (`atas`, cerca de 110 MB descompactado) e 78 MB
  (`atas_itens`). Cada ZIP traz um único CSV, em UTF-8 com BOM, separado por `;`
  e com os nomes das colunas na primeira linha.

## Instalação

Requer Python **3.10 ou superior**. Na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

No Linux/macOS, ative o ambiente com `source .venv/bin/activate`. Use `python3`
no lugar de `python` se necessário.

## Execução

```powershell
python src/coletores/coleta_arp.py --ano 2025
```

`--ano` é obrigatório e tem quatro dígitos. Sem outros parâmetros, baixa os dois
arquivos do ano, primeiro `atas` e depois `itens`. Para baixar só um deles, use
`--arquivo atas` ou `--arquivo itens`.

Para executar pelo Bash, de qualquer diretório, use os mesmos argumentos:

```bash
bash src/coletores/run-coleta-arp.sh --ano 2025
```

O wrapper usa o Python do `.venv` do repositório quando ele existe; caso
contrário, usa `python3` ou `python` do sistema. Funciona no Git Bash e no WSL.

## Saída

Cada download gera arquivos novos em `outputs/{ano}/`, na raiz do repositório,
qualquer que seja o diretório de execução. A pasta é ignorada pelo Git.

```text
outputs/{ano}/{AAAAMMDD}_{HHMMSS}_atas_{ano}.csv.zip
outputs/{ano}/{AAAAMMDD}_{HHMMSS}_atas_itens_{ano}.csv.zip
```

A data e a hora são as do início da execução, no horário local, iguais nos dois
arquivos, e indicam quando foram baixados, não a versão dos dados. Downloads
anteriores nunca são substituídos: as cópias se acumulam até serem removidas
manualmente.

### Escolher a pasta de saída

O parâmetro opcional `--pasta-saida` troca a pasta `outputs/{ano}/` por outra,
o que permite a outro repositório decidir onde os arquivos ficam. Os nomes
continuam automáticos, porque são dois arquivos:

```bash
bash /caminho/para/coletor-arp/src/coletores/run-coleta-arp.sh \
  --ano 2025 --pasta-saida tasks/coleta-arp/outputs/2025
```

Uma pasta relativa é resolvida a partir do diretório de onde o comando é
executado. Se algum dos arquivos de destino já existir, a coleta é recusada com
código 2, sem acessar a fonte.

O download é feito em streaming para um arquivo `.part` na mesma pasta. O nome
final só é usado depois que o arquivo chega inteiro, o total recebido confere com
o `Content-Length` e o conteúdo é reconhecido como ZIP. Em caso de falha, o
`.part` é removido. Os arquivos são pedidos sem compressão (`Accept-Encoding:
identity`), para que o conteúdo salvo seja exatamente o publicado.

Se o segundo arquivo falhar, o primeiro, já completo, permanece na pasta.

## Códigos de saída

| Código | Situação |
| --- | --- |
| **0** | Todos os arquivos pedidos foram salvos. |
| **1** | Falha de rede, HTTP diferente de 200 e 404, download incompleto, conteúdo que não é ZIP ou erro de escrita. |
| **2** | Argumento ou configuração inválidos, ano não publicado (404) ou destino já existente. |

## Configuração

As variáveis podem ser definidas no ambiente ou num `.env` na raiz do
repositório, usando `.env.example` como referência. O ambiente tem precedência.

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `REPOSITORIO_ARP_URL` | `https://repositorio.dados.gov.br/seges/comprasgov/arp` | Pasta das ARPs, HTTP(S), sem query ou fragmento. |
| `DOWNLOAD_TIMEOUT_SECONDS` | `60` | Timeout positivo, por tentativa, para conectar e entre leituras da resposta. |

Falhas de conexão e respostas HTTP **429, 500, 502, 503 e 504** são repetidas
até oito vezes, com espera crescente de fator 2 e respeito ao cabeçalho
`Retry-After`.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Os testes usam um servidor HTTP local e não acessam a fonte. Cobrem a
preservação byte a byte do ZIP, as URLs e os destinos dos dois arquivos, a
escolha de um só arquivo, ausência de `Content-Length`, 404 (sem deixar pasta
vazia) e outros status, download truncado, conteúdo que não é ZIP, falha no
segundo arquivo, retentativa após 503, validação do ano e da configuração,
`--pasta-saida` absoluta e relativa, destino já ocupado e o wrapper Bash chamado
de outro diretório.
