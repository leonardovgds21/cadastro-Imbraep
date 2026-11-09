"""E-mail aos colaboradores avisando os treinamentos na Inbraep.

O texto é o modelo da GAP: muda só a lista de treinamentos e a Data de
Início, que é a data do dia do envio. Login e senha são o CPF.

Endereço: a mesma regra do FormaSeg, primeironome.ultimonome@gapgestao.com.br
(sem acento, sem preposições e sem sufixo como Filho/Júnior; homônimos da
mesma lista recebem 2, 3...). Os endereços aparecem na tela antes de abrir o
e-mail e podem ser corrigidos.

O Outlook novo não tem a automação (COM) do Outlook clássico; nele o e-mail
abre por um link mailto:, que leva destinatários e assunto (links muito
longos são cortados pelo Windows).
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .config import DOMINIO_EMAIL, EMPRESA, URL_LOGIN
from .nomes import sem_acento

# O Windows aceita ~2048 caracteres num link; fica uma folga.
LIMITE_MAILTO = 1900
# Podem ir sem codificar no assunto/corpo de um mailto (RFC 6068), o que encurta o link.
SEGUROS = "!'()*,:@/"

SUFIXOS = {"filho", "filha", "junior", "jr", "neto", "neta", "sobrinho", "sobrinha", "segundo", "terceiro"}
PARTICULAS = {"da", "das", "de", "do", "dos", "e"}

ASSUNTO = "Treinamentos para atualização do certificado"

_RE_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def corpo(cursos: list[str], data_inicio: str) -> str:
    """O texto do modelo, com os treinamentos e a data de início."""
    lista = "\n".join(f"•  {c}" for c in cursos)
    return f"""Olá!

Segue treinamentos para atualização do certificado!

A empresa {EMPRESA} lhe inscreveu no curso de:

{lista}

Ficamos felizes que você esteja se aperfeiçoando.

Os cursos possuem conteúdos completos e vídeos para melhor fixação dos temas, conforme exigências do \
Ministério do Trabalho e Emprego e Secretaria de Estado da Educação e do Desporto.

O prazo padrão de término do curso é de 30 dias após a data de início, sendo que a empresa poderá \
estabelecer prazos menores caso necessário.

Data de Início: {data_inicio}

•  Login: seu CPF
•  Senha: seu CPF
•  Acesse: {URL_LOGIN}

Lembramos que a empresa irá acompanhar todo o seu desenvolvimento no curso, como acessos, conteúdos \
estudados, notas e certificação.

Bons estudos!

Qualquer dúvida entre em contato conosco."""


def _slug(palavra: str) -> str:
    return re.sub(r"[^a-z]", "", sem_acento(palavra).lower())


def email_base(nome_completo: str) -> str:
    """primeironome.ultimonome (sem acento, sem sufixo como Filho/Júnior)."""
    palavras = [p for p in (_slug(p) for p in nome_completo.split()) if p]
    if not palavras:
        return ""
    primeiro = palavras[0]
    resto = [p for p in palavras[1:] if p not in PARTICULAS]
    while len(resto) > 1 and resto[-1] in SUFIXOS:
        resto.pop()
    ultimo = resto[-1] if resto else ""
    return f"{primeiro}.{ultimo}" if ultimo else primeiro


def enderecos(nomes: list[str]) -> list[str]:
    """Um e-mail por nome, na regra nome.sobrenome; homônimos recebem 2, 3..."""
    usados: set[str] = set()
    saida = []
    for nome in nomes:
        base = email_base(nome)
        if not base:
            saida.append("")
            continue
        email, n = f"{base}@{DOMINIO_EMAIL}", 2
        while email in usados:
            email, n = f"{base}{n}@{DOMINIO_EMAIL}", n + 1
        usados.add(email)
        saida.append(email)
    return saida


def email_valido(email: str) -> bool:
    return bool(_RE_EMAIL.match(email.strip()))


def link_mailto(destinatarios: list[str], assunto: str, texto: str = "") -> str:
    """Link mailto: com destinatários separados por vírgula (RFC 6068)."""
    para = ",".join(quote(e, safe="@") for e in destinatarios)
    partes = [f"subject={quote(assunto, safe=SEGUROS)}"]
    if texto:
        partes.append(f"body={quote(texto.replace(chr(10), chr(13) + chr(10)), safe=SEGUROS)}")
    return f"mailto:{para}?{'&'.join(partes)}"


def preparar_link(destinatarios: list[str], assunto: str) -> tuple[str, bool]:
    """Devolve (link, com_destinatarios), tirando os destinatários se não couberem."""
    link = link_mailto(destinatarios, assunto)
    if len(link) <= LIMITE_MAILTO:
        return link, True
    return link_mailto([], assunto), False
