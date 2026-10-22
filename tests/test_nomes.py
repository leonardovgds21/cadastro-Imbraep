from cadastro_imbraep.nomes import mesmo_nome, nome_certificado, nomes_colados, ler_progresso
from cadastro_imbraep.plataforma import Matricula, termos_de_busca


def test_mesmo_nome_tolerante():
    assert mesmo_nome("Joao Carlos Soares Nascimento", "JOÃO CARLOS SOARES NASCIMENTO")
    assert mesmo_nome("Aline De Fatima Betti", "Aline de Fátima Betti")
    assert mesmo_nome("Cleyton Antonio Oliveira", "Cleyton Antônio de Oliveira")
    assert mesmo_nome("Bruno Oliveira", "Bruno Matias Gonçalo de Oliveira")
    assert not mesmo_nome("Bruno Oliveira", "Oliveira Bruno")
    assert not mesmo_nome("Gabriel Shalon", "Gabriel Godoi Candido")
    assert not mesmo_nome("Maria", "Maria Silva")


def test_nomes_colados():
    assert nomes_colados("Ana Souza\n\n1. Ana souza\nJosé Lima; Paulo Reis") == ["Ana Souza", "José Lima", "Paulo Reis"]


def test_progresso():
    assert ler_progresso("45%") == 45
    assert ler_progresso("87,5 %") == 87.5
    assert ler_progresso("-") is None
    assert Matricula("A", "C", "100%").concluida
    assert not Matricula("A", "C", "-").concluida


def test_nome_certificado():
    assert nome_certificado("MARIA DA SILVA", "NR 35: Trabalho em Altura") == "Maria da Silva - NR 35 Trabalho em Altura.pdf"


def test_termos_de_busca():
    assert termos_de_busca("Maria Clara Oliveira Macedo") == ["Maria Clara Oliveira Macedo", "maria macedo", "oliveira"]
    assert termos_de_busca("Renan Pereira") == ["Renan Pereira", "pereira"]
