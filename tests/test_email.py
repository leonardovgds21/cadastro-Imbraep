from cadastro_imbraep import email_alunos, email_html


def test_enderecos_regra_formaseg():
    assert email_alunos.enderecos(["Maria da Silva Souza", "João Pereira Filho", "Maria Souza", ""]) == [
        "maria.souza@gapgestao.com.br", "joao.pereira@gapgestao.com.br", "maria.souza2@gapgestao.com.br", ""]
    assert email_alunos.email_valido("maria.souza@gapgestao.com.br")
    assert not email_alunos.email_valido("maria souza@gap")


def test_corpo_do_modelo():
    texto = email_alunos.corpo(["NR-33 Supervisor de Entrada", "Curso digitado"], "09/11/2026")
    assert "•  NR-33 Supervisor de Entrada\n•  Curso digitado" in texto
    assert "Data de Início: 09/11/2026" in texto
    assert "Login: seu CPF" in texto and "Senha: seu CPF" in texto
    assert "https://inbraep.treinamento.online/login" in texto
    assert "GAP GESTÃO AMBIENTAL E PROJETOS LTDA." in texto


def test_html():
    html = email_html.montar_html(["NR-12 Ferramentas Manuais", "A & B"], "09/11/2026")
    assert "<li><b>NR-12 Ferramentas Manuais</b></li>" in html and "A &amp; B" in html
    assert "09/11/2026" in html and "1. Seus dados de acesso" in html


def test_mailto_sem_destinatarios_quando_nao_cabe():
    muitos = [f"pessoa{i}.sobrenome@gapgestao.com.br" for i in range(80)]
    link, com_dest = email_alunos.preparar_link(muitos, email_alunos.ASSUNTO)
    assert not com_dest and link.startswith("mailto:?subject=")
