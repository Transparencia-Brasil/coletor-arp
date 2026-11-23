"""Testes do coletor de atas de registro de preços, sem acesso à fonte pública."""

import io
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from src.coletores import coleta_arp as coletor

RAIZ = Path(__file__).resolve().parents[1]
LAST_MODIFIED = "Sat, 10 Oct 2026 11:03:11 GMT"
MOMENTO = datetime(2026, 11, 23, 10, 29, 15)


def zip_exemplo(nome):
    """ZIP pequeno com a mesma estrutura do publicado: um CSV em UTF-8 com BOM e ';'."""
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr(nome, '\ufeff"numero_ata_registro_preco";"id_compra"\r\n'
                               '"00001/2025";"16014305900012025"\r\n'.encode("utf-8"))
    return memoria.getvalue()


ATAS = zip_exemplo("atas_2025.csv")
ITENS = zip_exemplo("atas_itens_2025.csv")


def resposta(status=200, corpo=ATAS, cabecalhos=None, content_length=None):
    """Descreve uma resposta do servidor local.

    content_length=None declara o tamanho real do corpo; False omite o
    cabeçalho; um inteiro declara esse valor, mesmo que diferente do corpo.
    """
    return {"status": status, "corpo": corpo, "cabecalhos": cabecalhos or {},
            "content_length": content_length}


class ServidorLocal:
    """Servidor HTTP em thread que responde, em ordem, a respostas enfileiradas.

    Depois que a fila acaba, a última resposta é repetida. Usa HTTP/1.0, então
    cada resposta fecha a conexão, o que permite corpos menores que o tamanho
    declarado.
    """

    def __init__(self):
        self.respostas = [resposta()]
        self.caminhos = []
        self.cabecalhos_recebidos = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                servidor.caminhos.append(self.path)
                servidor.cabecalhos_recebidos.append(dict(self.headers))
                atual = servidor.respostas.pop(0) if len(servidor.respostas) > 1 else servidor.respostas[0]
                self.send_response(atual["status"])
                for nome, valor in atual["cabecalhos"].items():
                    self.send_header(nome, valor)
                if atual["content_length"] is None:
                    self.send_header("Content-Length", str(len(atual["corpo"])))
                elif atual["content_length"] is not False:
                    self.send_header("Content-Length", str(atual["content_length"]))
                self.end_headers()
                self.wfile.write(atual["corpo"])

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/base"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def fecha(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


class ComServidor(unittest.TestCase):
    """Base para testes que usam o servidor local e uma pasta temporária."""

    def setUp(self):
        self.servidor = ServidorLocal()
        self.addCleanup(self.servidor.fecha)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name)
        self.destino = self.pasta / "atas_2025.csv.zip"
        self.part = self.destino.with_name(self.destino.name + ".part")
        self.url = coletor.url_arquivo(coletor.Configuracao(self.servidor.base, 5.0), "atas", "2025")


class TestConfiguracao(unittest.TestCase):
    def configuracao_com(self, valores):
        """Lê a configuração com o ambiente isolado e sem ler o .env local."""
        with patch.dict(os.environ, valores, clear=True), patch.object(coletor, "load_dotenv"):
            return coletor.configuracao()

    def test_urls_dos_dois_arquivos(self):
        config = coletor.Configuracao("https://exemplo.gov.br/arp", 60.0)
        self.assertEqual(coletor.url_arquivo(config, "atas", "2025"),
                         "https://exemplo.gov.br/arp/2025/atas_2025.csv.zip")
        self.assertEqual(coletor.url_arquivo(config, "itens", "2025"),
                         "https://exemplo.gov.br/arp/2025/atas_itens_2025.csv.zip")

    def test_padroes(self):
        config = self.configuracao_com({})
        self.assertEqual(config.url_base, "https://repositorio.dados.gov.br/seges/comprasgov/arp")
        self.assertEqual(config.timeout, 60.0)

    def test_ambiente_tem_precedencia_e_barra_final_removida(self):
        config = self.configuracao_com({"REPOSITORIO_ARP_URL": "http://127.0.0.1:8000/base/",
                                        "DOWNLOAD_TIMEOUT_SECONDS": "5"})
        self.assertEqual(config.url_base, "http://127.0.0.1:8000/base")
        self.assertEqual(config.timeout, 5.0)

    def test_configuracao_invalida(self):
        for valores in (
            {"REPOSITORIO_ARP_URL": "ftp://exemplo.gov.br/arp"},
            {"REPOSITORIO_ARP_URL": "https://exemplo.gov.br/arp?a=1"},
            {"DOWNLOAD_TIMEOUT_SECONDS": "abc"},
            {"DOWNLOAD_TIMEOUT_SECONDS": "0"},
            {"DOWNLOAD_TIMEOUT_SECONDS": "inf"},
        ):
            with self.subTest(valores=valores), self.assertRaises(ValueError):
                self.configuracao_com(valores)

    def test_destino_com_data_e_hora_do_download(self):
        pasta = Path("saida")
        self.assertEqual(coletor.destino_arquivo(pasta, "atas", "2025", MOMENTO),
                         pasta / "20261123_102915_atas_2025.csv.zip")
        self.assertEqual(coletor.destino_arquivo(pasta, "itens", "2025", MOMENTO),
                         pasta / "20261123_102915_atas_itens_2025.csv.zip")


class TestArgumentos(unittest.TestCase):
    def test_sem_arquivo_baixa_os_dois(self):
        self.assertEqual(coletor.le_argumentos(["--ano", "2025"]), ("2025", ("atas", "itens"), None))

    def test_arquivo_e_pasta_de_saida(self):
        self.assertEqual(
            coletor.le_argumentos(["--ano", "2025", "--arquivo", "itens", "--pasta-saida", "x"]),
            ("2025", ("itens",), Path("x")),
        )

    def test_argumentos_invalidos(self):
        for argv in (["--ano", "25"], ["--ano", "２０２５"], ["--ano", "2025a"], [],
                     ["--ano", "2025", "--mes", "07"], ["--ano", "2025", "--arquivo", "contratos"]):
            with self.subTest(argv=argv), patch("sys.stderr"), self.assertRaises(SystemExit) as erro:
                coletor.le_argumentos(argv)
            self.assertEqual(erro.exception.code, 2)


class TestDownload(ComServidor):
    def baixa(self):
        with coletor.sessao_http() as sessao:
            return coletor.baixa_arquivo(sessao, self.url, self.destino, 5.0)

    def test_conteudo_identico_byte_a_byte(self):
        self.servidor.respostas = [resposta(cabecalhos={"Last-Modified": LAST_MODIFIED})]
        download = self.baixa()
        self.assertEqual(self.destino.read_bytes(), ATAS)
        self.assertEqual(download.bytes_gravados, len(ATAS))
        self.assertEqual(download.content_length, len(ATAS))
        self.assertEqual(download.last_modified, LAST_MODIFIED)
        self.assertEqual(self.servidor.caminhos, ["/base/2025/atas_2025.csv.zip"])
        self.assertFalse(self.part.exists())

    def test_pede_conteudo_sem_compressao(self):
        self.baixa()
        self.assertEqual(self.servidor.cabecalhos_recebidos[0].get("Accept-Encoding"), "identity")

    def test_corpo_maior_que_um_bloco(self):
        with patch.object(coletor, "TAMANHO_BLOCO", 7):
            self.baixa()
        self.assertEqual(self.destino.read_bytes(), ATAS)

    def test_sem_content_length(self):
        self.servidor.respostas = [resposta(content_length=False)]
        download = self.baixa()
        self.assertEqual(self.destino.read_bytes(), ATAS)
        self.assertIsNone(download.content_length)

    def test_404_nao_deixa_pasta(self):
        self.destino = self.pasta / "2030" / "atas_2030.csv.zip"
        self.servidor.respostas = [resposta(status=404, corpo=b"")]
        with self.assertRaises(coletor.AnoNaoPublicado):
            self.baixa()
        self.assertFalse(self.destino.parent.exists())

    def test_status_nao_200(self):
        self.servidor.respostas = [resposta(status=403, corpo=b"")]
        with self.assertRaises(requests.HTTPError):
            self.baixa()
        self.assertFalse(self.destino.exists())

    def test_truncado(self):
        self.servidor.respostas = [resposta(content_length=len(ATAS) + 100)]
        with self.assertRaises((coletor.DownloadIncompleto, requests.RequestException)):
            self.baixa()
        self.assertFalse(self.destino.exists())
        self.assertFalse(self.part.exists())

    def test_conteudo_que_nao_e_zip(self):
        # Uma página de erro servida com 200 não pode virar um .zip na pasta de saída.
        self.servidor.respostas = [resposta(corpo=b"<html>erro</html>")]
        with self.assertRaises(coletor.ArquivoInvalido):
            self.baixa()
        self.assertFalse(self.destino.exists())
        self.assertFalse(self.part.exists())

    def test_retentativa_503(self):
        self.servidor.respostas = [resposta(status=503, corpo=b""), resposta()]
        self.baixa()  # a primeira retentativa do urllib3 não espera
        self.assertEqual(self.destino.read_bytes(), ATAS)
        self.assertEqual(len(self.servidor.caminhos), 2)


class TestMain(ComServidor):
    def setUp(self):
        super().setUp()
        for contexto in (
            patch.dict(os.environ, {"REPOSITORIO_ARP_URL": self.servidor.base,
                                    "DOWNLOAD_TIMEOUT_SECONDS": "5"}),
            patch.object(coletor, "PASTA_SAIDA", self.pasta),
            patch.object(coletor, "datetime", wraps=datetime),
        ):
            contexto.start()
            self.addCleanup(contexto.stop)
        coletor.datetime.now.return_value = MOMENTO
        self.servidor.respostas = [resposta(cabecalhos={"Last-Modified": LAST_MODIFIED}),
                                   resposta(corpo=ITENS)]
        # Caminhos esperados escritos por extenso, sem usar destino_arquivo().
        self.atas = self.pasta / "2025" / "20261123_102915_atas_2025.csv.zip"
        self.itens = self.pasta / "2025" / "20261123_102915_atas_itens_2025.csv.zip"

    def executa(self, *argumentos):
        """Roda main() e devolve o código de saída e as mensagens registradas.

        Sem argumentos, pede o ano de 2025.
        """
        with self.assertLogs("coleta_arp", level="INFO") as log:
            codigo = coletor.main(list(argumentos) or ["--ano", "2025"])
        return codigo, "\n".join(log.output)

    def test_main_baixa_atas_e_itens(self):
        codigo, log = self.executa()
        self.assertEqual(codigo, 0)
        self.assertEqual(self.atas.read_bytes(), ATAS)
        self.assertEqual(self.itens.read_bytes(), ITENS)
        self.assertEqual(self.servidor.caminhos,
                         ["/base/2025/atas_2025.csv.zip", "/base/2025/atas_itens_2025.csv.zip"])
        self.assertIn(LAST_MODIFIED, log)
        self.assertIn(str(self.atas), log)
        self.assertIn(str(self.itens), log)

    def test_main_so_um_arquivo(self):
        self.servidor.respostas = [resposta(corpo=ITENS)]
        codigo, _ = self.executa("--ano", "2025", "--arquivo", "itens")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.itens.read_bytes(), ITENS)
        self.assertFalse(self.atas.exists())
        self.assertEqual(self.servidor.caminhos, ["/base/2025/atas_itens_2025.csv.zip"])

    def test_main_destino_existente_recusado_antes_de_baixar(self):
        self.itens.parent.mkdir(parents=True)
        self.itens.write_bytes(b"antigo")
        codigo, log = self.executa()
        self.assertEqual(codigo, 2)
        self.assertEqual(self.itens.read_bytes(), b"antigo")
        self.assertFalse(self.atas.exists())
        self.assertEqual(self.servidor.caminhos, [])
        self.assertIn(str(self.itens), log)

    def test_main_pasta_saida_absoluta(self):
        pasta = self.pasta / "outra"
        codigo, _ = self.executa("--ano", "2025", "--pasta-saida", str(pasta))
        self.assertEqual(codigo, 0)
        self.assertEqual((pasta / "20261123_102915_atas_2025.csv.zip").read_bytes(), ATAS)
        self.assertEqual((pasta / "20261123_102915_atas_itens_2025.csv.zip").read_bytes(), ITENS)
        self.assertFalse((self.pasta / "2025").exists())

    def test_main_pasta_saida_relativa_ao_diretorio_de_execucao(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio_anterior = os.getcwd()
            os.chdir(tmp)
            try:
                codigo, _ = self.executa("--ano", "2025", "--arquivo", "atas", "--pasta-saida", "dados")
            finally:
                os.chdir(diretorio_anterior)
            self.assertEqual(codigo, 0)
            self.assertEqual((Path(tmp) / "dados" / "20261123_102915_atas_2025.csv.zip").read_bytes(), ATAS)

    def test_main_404(self):
        self.servidor.respostas = [resposta(status=404, corpo=b"")]
        codigo, log = self.executa()
        self.assertEqual(codigo, 2)
        self.assertIn("Ano 2025 não publicado no repositório", log)
        self.assertFalse(self.atas.parent.exists())
        self.assertEqual(len(self.servidor.caminhos), 1)

    def test_main_falha_no_segundo_mantem_o_primeiro(self):
        self.servidor.respostas = [resposta(), resposta(corpo=b"<html>erro</html>")]
        codigo, _ = self.executa()
        self.assertEqual(codigo, 1)
        self.assertEqual(self.atas.read_bytes(), ATAS)
        self.assertFalse(self.itens.exists())

    def test_main_falhas_de_download_saem_com_1(self):
        for falha in (resposta(status=403, corpo=b""),
                      resposta(content_length=len(ATAS) + 100),
                      resposta(corpo=b"<html>erro</html>")):
            with self.subTest(status=falha["status"], corpo=falha["corpo"][:10]):
                self.servidor.respostas = [falha]
                codigo, _ = self.executa()
                self.assertEqual(codigo, 1)
                self.assertFalse(self.atas.exists())
                self.assertFalse(self.itens.exists())

    def test_main_argumentos_invalidos_nao_acessam_a_fonte(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as erro:
            coletor.main(["--ano", "25"])
        self.assertEqual(erro.exception.code, 2)
        self.assertEqual(self.servidor.caminhos, [])

    def test_main_configuracao_invalida(self):
        with patch.dict(os.environ, {"REPOSITORIO_ARP_URL": "https://x.gov.br/arp?a=1"}):
            codigo, log = self.executa()
        self.assertEqual(codigo, 2)
        self.assertIn("REPOSITORIO_ARP_URL", log)
        self.assertEqual(self.servidor.caminhos, [])


def bash_compativel():
    """Retorna um bash que aceite caminhos do Windows, ou None.

    No Windows, o primeiro bash do PATH costuma ser o do WSL, que não entende
    caminhos como C:/...; usa-se o do Git for Windows.
    """
    if os.name != "nt":
        return shutil.which("bash")
    for pasta in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if pasta and (Path(pasta) / "Git" / "bin" / "bash.exe").exists():
            return str(Path(pasta) / "Git" / "bin" / "bash.exe")
    caminho = shutil.which("bash")
    return caminho if caminho and "\\git\\" in caminho.lower() else None


class TestWrapper(unittest.TestCase):
    @unittest.skipUnless(bash_compativel(), "bash compatível indisponível")
    def test_wrapper_de_outro_diretorio_com_pasta_relativa(self):
        # Simula outro repositório chamando o wrapper com uma pasta própria.
        servidor = ServidorLocal()
        self.addCleanup(servidor.fecha)
        ambiente = {**os.environ, "REPOSITORIO_ARP_URL": servidor.base,
                    "DOWNLOAD_TIMEOUT_SECONDS": "5"}
        ambiente.pop("PYTHONIOENCODING", None)
        with tempfile.TemporaryDirectory() as tmp:
            processo = subprocess.run(
                [bash_compativel(), (RAIZ / "src" / "coletores" / "run-coleta-arp.sh").as_posix(),
                 "--ano", "2025", "--arquivo", "atas", "--pasta-saida", "outputs/2025"],
                cwd=tmp, env=ambiente, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(processo.returncode, 0, processo.stdout + processo.stderr)
            salvos = list((Path(tmp) / "outputs" / "2025").iterdir())
            self.assertEqual(len(salvos), 1)
            self.assertRegex(salvos[0].name, r"^\d{8}_\d{6}_atas_2025\.csv\.zip$")
            self.assertEqual(salvos[0].read_bytes(), ATAS)
        self.assertEqual(servidor.caminhos, ["/base/2025/atas_2025.csv.zip"])


if __name__ == "__main__":
    unittest.main()
