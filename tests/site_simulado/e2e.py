"""Teste de ponta a ponta da automação no site simulado (abre o Edge).

    python tests/site_simulado/e2e.py            (navegador invisível)
    python tests/site_simulado/e2e.py --mostrar  (vendo o navegador)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from servidor import iniciar  # noqa: E402

servidor, URL = iniciar()
os.environ["IMBRAEP_URL"] = URL
PASTA = Path(tempfile.mkdtemp(prefix="certificados_Imbraep_"))
os.environ["IMBRAEP_CERTIFICADOS"] = str(PASTA)

from cadastro_imbraep.entrada import ler_lista  # noqa: E402
from cadastro_imbraep.plataforma import ErroPlataforma, Plataforma  # noqa: E402

falhas = []


def confere(descricao, obtido, esperado):
    ok = obtido == esperado
    print(f"{'OK ' if ok else 'FALHOU'} {descricao}: {obtido!r}" + ("" if ok else f" (esperado {esperado!r})"))
    if not ok:
        falhas.append(descricao)


lista = ler_lista("""529.982.247-25 Maria da Silva
Pedro Ja Cadastrado 111.444.777-35
Rita Arquivada;39053344705
98765432100 Carlos Souza
123.123.123-87 José Teste""")

with Plataforma(log=lambda t: print("   log:", t), visivel="--mostrar" in sys.argv, espera=15) as p:
    try:
        p.login("000.000.000-00", "errada")
        confere("login errado recusado", "entrou", "recusado")
    except ErroPlataforma as erro:
        confere("login errado recusado", str(erro).startswith("Login recusado"), True)

    p.login("456.456.456-00", "teste")
    situacoes = [p.cadastrar(c, confirmar=True)[0] for c in lista[:4]]
    confere("cadastro", situacoes, ["cadastrado", "ja_cadastrado", "arquivado", "vinculado"])
    confere("modo teste", p.cadastrar(lista[4], confirmar=False)[0], "teste")
    confere("CPF recém-cadastrado vira já cadastrado", p.cadastrar(lista[0], confirmar=True)[0], "ja_cadastrado")

    m = p.acompanhamento("Joao Carlos Soares Nascimento")
    confere("acompanhamento João", [(x.curso, x.conclusao) for x in m], [("NR 35 - Trabalho em Altura", "45%")])
    m = p.acompanhamento("gabriel shalon")
    confere("acompanhamento Gabriel", [(x.curso, x.conclusao, x.concluida) for x in m],
            [("NR 10 - Básico", "80%", False), ("NR 33 - Supervisor de Entrada", "100%", True)])
    m = p.acompanhamento("Cleyton Antonio Oliveira")
    confere("acompanhamento sem preposição", [(x.aluno, x.conclusao) for x in m], [("Cleyton Antônio de Oliveira", "-")])
    confere("fora do acompanhamento", p.acompanhamento("Aline De Fatima Betti"), [])

    h = p.historico("Aline De Fatima Betti")
    confere("histórico Aline", [(x.aluno, x.curso) for x in h], [("Aline de Fátima Betti", "NR 06 - EPI")])
    arquivo = p.baixar_certificado(h[0], PASTA)
    confere("certificado com assinatura", (arquivo.name, arquivo.read_bytes()[:4], b"11-com" in arquivo.read_bytes()),
            ("Aline de Fátima Betti - NR 06 - EPI.pdf", b"%PDF", True))
    h = p.historico("Gabriel Shalon")
    arquivo = p.baixar_certificado(h[0], PASTA)
    confere("certificado sem assinatura", b"12-sem" in arquivo.read_bytes(), True)
    confere("não encontrado", (p.acompanhamento("Fulano Inexistente"), p.historico("Fulano Inexistente")), ([], []))

servidor.shutdown()
print("\nCertificados em", PASTA)
print("TUDO CERTO" if not falhas else f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
sys.exit(1 if falhas else 0)
