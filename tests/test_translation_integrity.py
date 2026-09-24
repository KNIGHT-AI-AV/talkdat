import io,json,unittest
from unittest.mock import patch
from knight_flow import translation as module


class TranslationIntegrityTests(unittest.TestCase):
    def test_currency_percent_and_negative_sign_are_inside_protection(self):
        source='Pay $14.99, keep 100%, reduce by -5 and add €12.50.'
        masked,values=module._mask_protected(source)
        for value in ('$14.99','100%','-5','€12.50'):
            self.assertIn(value,values.values())
        self.assertEqual(module._restore_protected(masked,values),source)
    def test_literal_placeholder_syntax_roundtrips(self):
        source='The literal is __TD_KEEP_000__, then version 1.2.'
        masked,values=module._mask_protected(source)
        self.assertEqual(module._restore_protected(masked,values),source)
    def test_placeholder_inside_original_link_is_not_reinterpreted(self):
        source='Open https://example.com/__TD_KEEP_001__ and use 2.4.'
        masked,values=module._mask_protected(source)
        self.assertEqual(module._restore_protected(masked,values),source)
    def test_unknown_four_digit_placeholder_is_rejected(self):
        with self.assertRaises(module.TranslationError):module._restore_protected('word __TD_KEEP_1000__',{})
    def test_chunks_keep_a_boundary_link_intact(self):
        link='https://example.com/order/123456?code=ABCDEFGHIJK'
        source='word '*636+' '+link+' next sentence.'
        chunks=module._chunks(source)
        self.assertTrue(any(link in chunk for chunk in chunks))
        self.assertEqual(''.join(chunks),source)
    def test_chunks_do_not_split_a_word(self):
        word='internationalization'
        source='word '*638+word+' ends here.'
        chunks=module._chunks(source)
        self.assertTrue(any(word in chunk for chunk in chunks))
        self.assertTrue(all(len(chunk)<=3200 for chunk in chunks))
    def translate_echo(self,text,reason='stop'):
        def answer(request,**kwargs):
            prompt=json.loads(request.data)['messages'][0]['content']
            return io.BytesIO(json.dumps({'message':{'content':prompt.rsplit('\n\n\n',1)[-1].strip()},'done_reason':reason}).encode())
        with patch('urllib.request.urlopen',side_effect=answer),patch('knight_flow.net_fence.assert_cloud_allowed'):
            return module._translate_chunk(text,module.language_from_value('en'),module.language_from_value('es'),
                model=module.DEFAULT_TRANSLATION_MODEL,api_base='http://localhost:11434',timeout=5,
                formality='natural',preserve_formatting=True,glossary=[])
    def test_translation_retains_outer_spaces_and_line_boundaries(self):
        source='  First line.\nSecond line.\n'
        self.assertEqual(self.translate_echo(source),source)
    def test_truncated_model_result_is_not_reported_as_complete(self):
        with self.assertRaises(module.TranslationError):self.translate_echo('A full sentence.',reason='length')
    def test_invalid_explicit_source_is_not_silently_english(self):
        with self.assertRaises(module.TranslationError):module.resolve_source_language({},'unsupported-language')
    def test_long_ideographic_passage_retains_every_character(self):
        source='这是用于验证分段的中文段落。'*500
        chunks=module._chunks(source)
        self.assertEqual(''.join(chunks),source)
        self.assertTrue(all(len(chunk)<=3200 for chunk in chunks))
    def test_unbroken_oversized_protected_link_fails_without_slicing(self):
        with self.assertRaises(module.TranslationError):module._chunks('https://example.com/'+('a'*4000))
    def test_many_protected_values_and_literal_placeholders_roundtrip(self):
        source=' '.join(str(index) for index in range(1100))+' __TD_KEEP_1001__'
        masked,protected=module._mask_protected(source)
        self.assertEqual(module._restore_protected(masked,protected),source)
    def test_chunks_rejoin_exactly_for_varied_multiline_documents(self):
        for phrase in ('A short sentence. ', '  Item 12 costs $14.99.\n', '中文段落。', 'Email person@example.com\n\n'):
            for length in (1,40,3200):
                source=phrase*200
                if length==1:
                    if phrase!='中文段落。':continue
                chunks=module._chunks(source,length)
                self.assertEqual(''.join(chunks),source)
                self.assertTrue(all(len(chunk)<=length for chunk in chunks))
    def test_repeated_sentences_keep_their_exact_count_and_spacing(self):
        source=('Do not change this paragraph. '*21)+'Keep the last sentence.'
        chunks=module._chunks(source)
        self.assertEqual(''.join(chunks),source)
        self.assertEqual(chunks.count('Do not change this paragraph. '),21)
    def test_sentence_boundaries_do_not_split_protected_links(self):
        source=('See https://example.com/a. Keep the reference.\n'*6)+'Done.'
        self.assertEqual(''.join(module._sentence_parts(source)),source)
        self.assertTrue(all('https://' not in part or 'https://example.com/a.' in part for part in module._sentence_parts(source)))
    def test_multiple_repeated_runs_leave_intervening_text_intact(self):
        source=('First sentence!\n'*4)+'A unique middle sentence. '+('Last sentence? '*7)
        self.assertEqual(''.join(module._chunks(source)),source)
        self.assertEqual(module._chunks(source).count('Last sentence? '),7)
    def test_empty_and_whitespace_chunks_do_not_contact_the_engine(self):
        with patch('urllib.request.urlopen') as send:
            self.assertEqual(self.translate_echo('\n  \t'),'\n  \t')
            send.assert_not_called()
    def test_mac_runtime_can_be_found_without_a_path_symlink(self):
        with patch.object(module.sys,'platform','darwin'),patch.object(module.shutil,'which',return_value=None),patch.object(module.os.path,'isfile',return_value=True):
            self.assertEqual(module._ollama_executable(),'/Applications/Ollama.app/Contents/Resources/ollama')
    def test_mac_install_never_attempts_windows_package_manager(self):
        with patch.object(module.sys,'platform','darwin'),patch.object(module,'_ollama_executable',return_value=''),patch.object(module.shutil,'which') as which:
            ready,message=module.install_ollama_runtime()
            self.assertFalse(ready)
            self.assertIn('Applications',message)
            which.assert_not_called()
    def translate_payload(self,payload,text='A source sentence.'):
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())),patch('knight_flow.net_fence.assert_cloud_allowed'):
            return module._translate_chunk(text,module.language_from_value('en'),module.language_from_value('es'),model=module.DEFAULT_TRANSLATION_MODEL,api_base='http://localhost:11434',timeout=5,formality='natural',preserve_formatting=True,glossary=[])
    def test_malformed_or_unfinished_engine_response_is_not_text(self):
        for payload in ([],{'message':{'content':42}},{'done':False,'message':{'content':'partial'}},{'error':'failed','message':{'content':'partial'}}):
            with self.subTest(payload=payload),self.assertRaises(module.TranslationError):self.translate_payload(payload)
    def test_unexpected_repeated_output_is_refused(self):
        with self.assertRaises(module.TranslationError):self.translate_payload({'message':{'content':'Una frase. '*8}})
    def test_three_repeated_inputs_use_one_translation_and_keep_count(self):
        with patch.object(module,'translation_model_status',return_value={'engine_installed':True,'engine_running':True,'model_installed':True}),patch.object(module,'_translate_chunk',return_value='Una frase. ') as send:
            result=module.translate_text('A sentence. '*3,{},source_value='en',target_value='es')
            self.assertEqual(result.text,'Una frase. '*3)
            send.assert_called_once()
    def test_cancelled_request_never_starts_inference(self):
        with patch.object(module,'translation_model_status') as status,self.assertRaises(module.TranslationError) as caught:
            module.translate_text('Hello',{},source_value='en',target_value='es',cancelled=lambda:True)
        self.assertEqual(caught.exception.code,'cancelled')
        status.assert_not_called()
    def test_cancellation_after_a_response_prevents_returning_its_result(self):
        stopped=False
        def complete(*args,**kwargs):
            nonlocal stopped
            stopped=True
            return 'Hola'
        with patch.object(module,'translation_model_status',return_value={'engine_installed':True,'engine_running':True,'model_installed':True}),patch.object(module,'_translate_chunk',side_effect=complete),self.assertRaises(module.TranslationError) as caught:
            module.translate_text('Hello',{},source_value='en',target_value='es',cancelled=lambda:stopped)
        self.assertEqual(caught.exception.code,'cancelled')
    def test_invalid_tag_response_is_an_unavailable_engine(self):
        for payload in ([],{'models':None},{'models':42}):
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
                self.assertIsNone(module._ollama_models('http://localhost:11434'))

if __name__=='__main__':unittest.main()
