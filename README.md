# Cadastro Imbraep

App desktop (Windows) que automatiza, na plataforma de treinamentos
Inbraep (AVAPRO, https://inbraep.treinamento.online):

- **Cadastro de colaboradores**: cola CPF e nome completo (vários de uma vez),
  o app entra como "Responsável" e cadastra cada um em
  Colaboradores > Cadastrar. CPF já cadastrado é pulado e avisado.
- **Monitoramento**: cola os nomes; o app lê o Acompanhamento (curso e
  Conclusão %) e, para quem não está lá, procura em Histórico e Certificados
  e baixa o certificado (com assinatura, se houver) para a pasta
  `certificados_Imbraep` na Área de Trabalho.

Não cadastra nem compra treinamentos.

## Uso

Baixe a pasta `executavel/CadastroImbraep` e rode `CadastroImbraep.exe`
(instruções no `LEIA-ME.txt`). O login é pedido na hora e, se marcado,
fica só no Cofre de Credenciais do Windows.

## Desenvolvimento

- Python 3.12, Tkinter, Selenium (Edge), keyring, PyInstaller.
- `python main.py` abre o app; `python -m pytest -q tests` roda os testes.
- `tests/site_simulado/` tem um site que imita as telas da plataforma:
  `python tests/site_simulado/e2e.py` testa a automação de ponta a ponta nele.
- `build.bat` gera `executavel/CadastroImbraep` (pasta portátil).
