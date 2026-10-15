import io
import unittest
import zipfile
from reprovacoes_whatsapp import consolidar, importar_zip, ler_pdf, Repositorio, extrair_itens, detalhar_itens


def registro(id='r', placa='ABC1D23', resultado='REPROVADO', impressao='2026-10-01T10:00', dia='2026-10-01', numero='123'):
    return dict(id=id, frota='13773', placa=placa, numero=numero, resultado=resultado,
                vistoria=dia+'T08:00', impressao=impressao, evento='ITR')


class TestReprovacoes(unittest.TestCase):
    def test_itens_colunas_continuacao_e_fotos(self):
        import pymupdf
        d=pymupdf.open();p=d.new_page(width=794,height=595)
        p.insert_text((138,540),'5.3. CIRCUITO DE FREIO:')
        p.insert_text((138,558),'Mangotes e valvulas')
        p.insert_text((286,540),'NÃO CONFORME')
        p.insert_text((412,540),'5.4. TAMBOR:')
        p.insert_text((412,558),'Conservacao.:')
        p.insert_text((560,540),'CONFORME')
        p=d.new_page(width=794,height=595)
        p.insert_text((138,35),'Conexoes.:')
        p.insert_text((138,50),'Observação:Fixar mangote')
        p.insert_text((138,100),'5.5. ABS:')
        p.insert_text((286,100),'NÃO CONFORME')
        p.insert_text((138,200),'FOTOS DO CHECKLIST')
        p.insert_text((138,240),'5.3. CIRCUITO DE FREIO:')
        p.insert_text((286,240),'NÃO CONFORME')
        itens=extrair_itens(d.tobytes());d.close()
        self.assertEqual([x['codigo'] for x in itens],['5.3','5.5'])
        self.assertEqual(itens[0]['observacao'],'Fixar mangote')
        self.assertIn('Conexoes',itens[0]['descricao'])

    def test_ranking_nao_duplica_item_em_versoes(self):
        r=registro();r['itens_reprovados']=[dict(codigo='5.3',item='Freio',descricao='Freio',observacao='Fixar',pagina=2)]
        s=dict(r,id='nova-versao')
        a=dict(r,id='aprovacao',resultado='APROVADO')
        self.assertEqual(len(detalhar_itens([r,s,a])),1)

    def test_reimportacao_nao_duplica(self):
        r=registro()
        self.assertEqual(consolidar([r,r])[0]['Laudos reprovados'],1)

    def test_aprovacao_preserva_reprovacao(self):
        a=registro('a',resultado='APROVADO',impressao='2026-10-01T11:00')
        r=consolidar([registro(),a])[0]
        self.assertEqual(r['Situação'],'Aprovada na reinspeção')
        self.assertEqual(r['Laudos reprovados'],1)

    def test_outra_placa_nao_baixa(self):
        a=registro('a',placa='ZZZ9Z99',resultado='APROVADO')
        r=consolidar([registro(),a])[0]
        self.assertEqual(r['Situação'],'Pendente')
        self.assertIn('ZZZ9Z99',r['Conferência'])

    def test_reinspecao_mesma_impressao(self):
        a=registro('a',resultado='APROVADO')
        self.assertEqual(consolidar([registro(),a])[0]['Situação'],'Aprovada na reinspeção')

    def test_outro_laudo_nao_baixa(self):
        a=registro('a',numero='999',resultado='APROVADO')
        self.assertEqual(consolidar([registro(),a])[0]['Situação'],'Pendente')

    def test_aprovacao_anterior_nao_baixa(self):
        a=registro('a',resultado='APROVADO',impressao='2026-10-01T09:00')
        self.assertEqual(consolidar([registro(),a])[0]['Situação'],'Pendente')

    def test_nova_reprovacao_reabre(self):
        a=registro('a',resultado='APROVADO',impressao='2026-10-01T11:00')
        b=registro('b',impressao='2026-10-01T12:00')
        self.assertEqual(consolidar([registro(),a,b])[0]['Situação'],'Pendente')

    def test_outro_dia_independente(self):
        b=registro('b',dia='2026-10-02',impressao='2026-10-02T12:00')
        self.assertEqual(len(consolidar([registro(),b])),2)

    def test_zip_com_pdf_invalido_continua(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('ruim.pdf',b'invalido')
        regs,pdfs,avisos,msg=importar_zip(b.getvalue())
        self.assertEqual(regs,[])
        self.assertTrue(any('ruim.pdf' in a for a in avisos))

    def test_pdf_renomeado_tem_mesma_identidade(self):
        import pymupdf
        d=pymupdf.open();p=d.new_page()
        p.insert_text((40,40),'REPROVADO\nNumeração: 123\nPlaca: ABC1D23\nNr Chassi/GO: 13773\nData Vistoria: 01/10/2026 08:00\nData Impressão: 01/10/2026 10:00')
        pdf=d.tobytes();d.close()
        self.assertEqual(ler_pdf(pdf,'x.pdf')['id'],ler_pdf(pdf,'y.pdf')['id'])


if __name__=='__main__': unittest.main()
