# Aplicativos com base local

Implementação em desenvolvimento. A tela Aplicativos integrados consulta SQLite; abrir um módulo não abre o aplicativo online. Os cadastros, movimentações e consultas específicos dos aplicativos originais ainda precisam ser portados além desta camada de consulta e histórico.

## Regra de persistência

- A rede alimenta o banco; todas as consultas dessas telas leem SQLite.
- Cada conjunto usa uma chave estável. Repetir a alimentação não duplica registros nem alterações.
- Atualizações ficam em `change_history`, com usuário/origem, horário UTC e JSON antes/depois.
- Registros ausentes de uma extração completa recebem `_source_present=0`. Continuam no banco e podem ser consultados com Incluir ausentes da origem.
- Uma carga com erro é revertida integralmente, inclusive histórico e metadados. A última base permanece disponível.
- Alimentações anteriores ou conflitantes são rejeitadas pelo carimbo `source_at`.
- Backup inclui banco e histórico. Não é necessário manter o aplicativo original aberto.
- Não envia alterações locais para os servidores originais.

## Situação das fontes

| Aplicativo | Fonte já existente | Complemento necessário |
|---|---|---|
| ASN | Leitura paginada de monitor_asn | Mantém fluxo SharePoint atual; consulta não força Power Automate |
| Veículos | Veículos, movimentações e relatórios de consumo | Confirmar abrangência da origem |
| Estoque do socorro | Relatório autenticado de saldos/reposição | Cadastro completo, movimentações e inventários |
| Financeiro | Cópias de consultas feitas na versão anterior, se existentes | Exportador autenticado completo para nova alimentação |
| Gestão do socorro / socorrista | Cópias da versão anterior, se existentes | Exportador completo, incluindo referências a evidências |
| Pneus | Contrato local e importação prontos | Exportador de pneus e movimentações |
| Propostas | Cópias anteriores, se existentes | Exportador de propostas |
| PCM | Contrato local e importação prontos | Exportador de solicitações e itens |
| Lean | Contrato local e importação prontos | Exportador de projetos, itens e movimentações |

Não há dados fictícios nas telas de produção. Um conjunto nunca alimentado aparece como Aguardando primeira alimentação. Um conjunto completo vazio aparece como Disponível offline com zero registros. Receber somente reposição não indica que o estoque completo está integrado.

## Contrato do exportador

O aplicativo original deve oferecer um endpoint HTTPS autenticado, no seu próprio domínio, que retorne a extração abaixo. O exportador agrega todas as páginas antes de declarar `complete=true`. Neste momento esses novos exportadores NÃO foram publicados nos aplicativos originais.

```json
{
  "version": 1,
  "module": "Estoque do socorro",
  "complete": true,
  "source_at": "2026-11-14T12:00:00-03:00",
  "datasets": {
    "itens": [{"id":"ITEM-1","ni":"123","descricao":"Material"}],
    "movimentacoes": [{"id":"MOV-1","item_id":"ITEM-1","quantidade":2,"tipo":"Saída"}],
    "inventarios": [],
    "reposicao": [{"ni":"123","estoque_atual_total":10}]
  }
}
```

`complete=true` declara que cada conjunto incluído está completo. Conjuntos omitidos são preservados e continuam pendentes caso nunca tenham sido recebidos. Use arrays vazios somente quando a fonte confirmar que não há registros naquele conjunto. Inclua todos os históricos disponíveis na primeira carga. O portal não pode recuperar alterações da origem ocorridas antes da integração que não tenham sido armazenadas na própria origem.

Tabelas e chaves permitidas são definidas em `offline_modules.DATASETS`. Não aceita nome de tabela arbitrário, colunas reservadas ou credenciais nos registros. Anexos referenciados apenas por URL ainda precisam de download separado para serem abertos offline; esta implementação não afirma que evidências remotas foram copiadas.

É possível importar o JSON na tela de cada aplicativo. Para atualização automática (a cada minuto, com portal aberto), o administrador importa uma conexão JSON com `endpoint` e `headers`. Configure apenas chave de leitura no cabeçalho; nunca coloque segredo na URL. A conexão é criptografada por DPAPI neste usuário Windows. Redirecionamentos são recusados para impedir envio dos cabeçalhos a outro endereço. Limite de pacote: 50 MiB.

Quando um exportador completo é configurado para veículos ou estoque, ele substitui o conector legado daquele módulo para evitar que a mesma tabela receba duas fontes concorrentes. Uma falha não faz o portal retornar silenciosamente a uma fonte antiga.

## Validação

Executar em `desktop`: `python -m unittest discover -s tests -v`.

Os testes verificam todos os nove módulos após reiniciar a base sem rede, histórico antes/depois, ausência e reaparecimento, idempotência, rejeição de carga parcial/antiga, reversão atômica, permissões e backup/restauração. Não equivalem à validação dos exportadores reais ainda pendentes.
