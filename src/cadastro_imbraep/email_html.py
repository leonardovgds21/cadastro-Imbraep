"""O e-mail aos colaboradores no padrão visual da GAP (HTML) e a abertura no Outlook.

O texto é o mesmo de email_alunos.corpo(), só organizado em blocos: logo,
saudação, caixa de destaque com os treinamentos, seções numeradas e tabela
com a data de início e os dados de acesso. O HTML usa só tabelas e estilos na
própria tag, que é o que o Outlook mostra direito.

Abertura (do melhor para o mais simples):
1. Outlook clássico (automação COM): rascunho já formatado, com a logo embutida.
2. Senão (ex.: Outlook novo, que não tem COM): o link mailto abre o e-mail
   com destinatários e assunto, e o texto formatado vai para a área de
   transferência para colar com Ctrl+V.
"""

from __future__ import annotations

import base64
import html
import sys
import time
from pathlib import Path

from .config import EMPRESA, URL_LOGIN, recurso

VERDE = "#2e7d32"
VERDE_ESCURO = "#1b5e20"
VERDE_CLARO = "#e8f5e9"
AZUL = "#1f4e79"
CINZA = "#f2f2f2"
TEXTO = "#333333"
ID_LOGO = "logo_gap"


def arquivo_logo() -> Path | None:
    """assets/logo_gap.png, se existir (vai junto no executável)."""
    caminho = recurso("assets/logo_gap.png")
    return caminho if caminho.exists() else None


def _logo(src: str | None) -> str:
    if src:
        return f'<img src="{src}" alt="GAP" height="48" style="display:block;border:0;height:48px">'
    # sem o arquivo da logo: "GAP" em texto, nas cores da marca
    return (f'<span style="font:bold 30px Arial,sans-serif;color:{VERDE}">&#10138;</span>'
            f'<span style="font:bold 30px Arial,sans-serif;color:{AZUL};letter-spacing:1px">GAP</span>')


def _secao(numero: int, titulo: str) -> str:
    return (f'<tr><td style="padding:22px 0 8px 0">'
            f'<div style="border-left:4px solid {VERDE};padding-left:10px;font:bold 17px Arial,sans-serif;'
            f'color:{VERDE_ESCURO}">{numero}. {html.escape(titulo)}</div></td></tr>')


def _paragrafo(texto: str, estilo: str = "") -> str:
    return (f'<tr><td style="padding:6px 0;font:15px/1.5 Arial,sans-serif;color:{TEXTO};{estilo}">'
            f'{texto}</td></tr>')


def _linha_tabela(rotulo: str, valor: str) -> str:
    return (f'<tr><td style="background:{CINZA};padding:9px 12px;font:bold 14px Arial,sans-serif;color:#555;'
            f'width:170px;border-bottom:1px solid #ffffff">{html.escape(rotulo)}</td>'
            f'<td style="padding:9px 12px;font:14px Arial,sans-serif;color:{TEXTO};border-bottom:1px solid {CINZA}">'
            f'{valor}</td></tr>')


def montar_html(cursos: list[str], data_inicio: str, logo_src: str | None = None) -> str:
    """O e-mail completo em HTML. `logo_src` é "cid:..." (Outlook) ou "data:..." (colar)."""
    e = html.escape
    itens = "".join(f"<li><b>{e(c)}</b></li>" for c in cursos)
    linhas = [
        f'<tr><td style="padding:0 0 18px 0;border-bottom:3px solid {VERDE}">{_logo(logo_src)}</td></tr>',
        _paragrafo('<span style="font-size:17px"><b>Olá!</b></span>', "padding-top:18px"),
        _paragrafo("Segue treinamentos para atualização do certificado!"),
        f'<tr><td style="padding:10px 0"><div style="background:{VERDE_CLARO};border-left:5px solid {VERDE};'
        f'padding:14px 16px;font:15px/1.5 Arial,sans-serif;color:{VERDE_ESCURO}">'
        f'A empresa <b>{e(EMPRESA)}</b> lhe inscreveu no curso de:'
        f'<ul style="margin:8px 0 0 0;padding-left:22px">{itens}</ul></div></td></tr>',
        _paragrafo("Ficamos felizes que você esteja se aperfeiçoando."),
        _paragrafo(e("Os cursos possuem conteúdos completos e vídeos para melhor fixação dos temas, conforme "
                     "exigências do Ministério do Trabalho e Emprego e Secretaria de Estado da Educação e do "
                     "Desporto.")),
        _secao(1, "Seus dados de acesso"),
        '<tr><td><table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        'style="border-collapse:collapse">'
        + _linha_tabela("Data de Início", f"<b>{e(data_inicio)}</b>")
        + _linha_tabela("Login", "seu CPF")
        + _linha_tabela("Senha", '<span style="font-family:Consolas,Courier New,monospace">seu CPF</span>')
        + _linha_tabela("Acesse", f'<a href="{e(URL_LOGIN)}" style="color:{AZUL}">{e(URL_LOGIN)}</a>')
        + "</table></td></tr>",
        _secao(2, "Prazo e acompanhamento"),
        _paragrafo(e("O prazo padrão de término do curso é de 30 dias após a data de início, sendo que a empresa "
                     "poderá estabelecer prazos menores caso necessário.")),
        _paragrafo(e("Lembramos que a empresa irá acompanhar todo o seu desenvolvimento no curso, como acessos, "
                     "conteúdos estudados, notas e certificação.")),
        _paragrafo("<b>Bons estudos!</b>", "padding-top:18px"),
        f'<tr><td style="padding:18px 0 0 0;border-top:1px solid {CINZA};font:13px Arial,sans-serif;color:#777">'
        f'Qualquer dúvida entre em contato conosco.</td></tr>',
    ]
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            '<body style="margin:0;padding:0;background:#ffffff">'
            '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr><td align="left" '
            'style="padding:20px">'
            '<table role="presentation" cellpadding="0" cellspacing="0" width="640" style="max-width:640px">'
            + "".join(linhas) + "</table></td></tr></table></body></html>")


def logo_data_uri() -> str | None:
    logo = arquivo_logo()
    if not logo:
        return None
    return "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode()


# ---------- Outlook clássico (COM) ----------
def abrir_no_outlook(destinatarios: list[str], assunto: str, cursos: list[str], data_inicio: str) -> bool:
    """Cria o rascunho formatado no Outlook clássico e mostra na tela.
    Devolve False se o Outlook clássico não estiver disponível."""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # pywin32
    except ImportError:
        return False
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        email = outlook.CreateItem(0)  # olMailItem
        email.To = "; ".join(destinatarios)
        email.Subject = assunto
        logo = arquivo_logo()
        if logo:
            anexo = email.Attachments.Add(str(logo), 1, 0)
            # PR_ATTACH_CONTENT_ID: a imagem fica no corpo, não como anexo
            anexo.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", ID_LOGO)
        email.HTMLBody = montar_html(cursos, data_inicio, f"cid:{ID_LOGO}" if logo else None)
        email.Display()
        return True
    except Exception:  # Outlook novo, Outlook fechado com erro, perfil não configurado...
        return False


# ---------- área de transferência com HTML ----------
def _cf_html(fragmento: str) -> bytes:
    """O formato "HTML Format" do Windows: cabeçalho com as posições em bytes."""
    modelo = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
              "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
    inicio, fim = "<html><body><!--StartFragment-->", "<!--EndFragment--></body></html>"
    tam_cab = len(modelo.format(0, 0, 0, 0).encode())
    corpo = fragmento.encode("utf-8")
    start_html = tam_cab
    start_frag = start_html + len(inicio.encode())
    end_frag = start_frag + len(corpo)
    end_html = end_frag + len(fim.encode())
    return (modelo.format(start_html, end_html, start_frag, end_frag).encode()
            + inicio.encode() + corpo + fim.encode())


def copiar_html(html_completo: str, texto: str, janela: int | None = None) -> bool:
    """Põe o e-mail na área de transferência como HTML (cola formatado no
    Outlook) e como texto simples. Devolve False fora do Windows ou se falhar.

    `janela` é o identificador (HWND) da janela do app: com ele a área de
    transferência fica com dono. Sem dono (OpenClipboard(NULL)), o Windows
    pode recusar os dados e o e-mail cola em branco."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    corpo = html_completo.split("<body", 1)[-1].split(">", 1)[-1].rsplit("</body>", 1)[0]
    dados_html = _cf_html(corpo) + b"\0"
    dados_texto = (texto + "\0").encode("utf-16-le")

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.OpenClipboard.argtypes = [wintypes.HWND]

    def colocar(formato: int, dados: bytes) -> bool:
        memoria = kernel32.GlobalAlloc(0x0002, len(dados))  # GMEM_MOVEABLE
        if not memoria:
            return False
        ponteiro = kernel32.GlobalLock(memoria)
        ctypes.memmove(ponteiro, dados, len(dados))
        kernel32.GlobalUnlock(memoria)
        return bool(user32.SetClipboardData(formato, memoria))

    for _ in range(5):  # outro programa pode estar com a área de transferência aberta
        if user32.OpenClipboard(janela):
            break
        time.sleep(0.1)
    else:
        return False
    try:
        user32.EmptyClipboard()
        ok = colocar(user32.RegisterClipboardFormatW("HTML Format"), dados_html)
        ok = colocar(13, dados_texto) and ok  # CF_UNICODETEXT
        return ok
    finally:
        user32.CloseClipboard()
