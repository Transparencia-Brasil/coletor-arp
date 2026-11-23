# Coletor de atas de registro de preços

Data: 2026-11-23. Status: implementado.

## Objetivo

Baixar, para um ano informado, as atas de registro de preços (ARP) do Compras.gov.br e
salvá-las exatamente como vieram, para uso no repositório `medicamentos-fdcc`. A coleta
deve ser simples e seguir a lógica dos outros coletores; tratamento e cruzamento ficam
fora daqui.

## Fonte

`https://repositorio.dados.gov.br/seges/comprasgov/arp/`, com uma pasta por ano (2023 a
2026) e dois arquivos em cada: `atas_{ano}.csv.zip` e `atas_itens_{ano}.csv.zip`.

O pedido era ter coleta anual, mensal ou diária, como no `coletor-contratos`. A fonte não
publica arquivos mensais nem diários, só os anuais. Um recorte por mês exigiria abrir o
CSV e filtrar as linhas por data, o que é tratamento de dado e fica fora do coletor.

## Decisões

- `--ano` é o único parâmetro de período. Sem `--arquivo`, os dois arquivos do ano são
  baixados, porque as atas e os itens são usados juntos; `--arquivo atas|itens` baixa só um.
- `--pasta-saida` no lugar do `--saida` dos outros coletores: são dois arquivos, então
  quem chama escolhe a pasta e os nomes continuam automáticos (data e hora mais o nome
  publicado na fonte).
- Os destinos dos dois arquivos são conferidos antes do primeiro download; se um já
  existir, nada é baixado. Se o segundo download falhar, o primeiro, completo, fica.
- O resto segue o `coletor-empenhos`: ZIP salvo inteiro, sem descompactar; `.part` com
  troca atômica; conferência do `Content-Length` e de que o conteúdo é um ZIP; pasta
  criada só depois da resposta 200; retentativas para falhas transitórias.
