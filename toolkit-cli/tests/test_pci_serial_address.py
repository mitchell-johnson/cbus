"""Pure selected-serial codec: independent native vectors, no TCP fixture."""
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.pci_serial_address import encode_serial_address, decode_serial_address_receipt


A='101136.1558'
B='101136.1559'
FRAME_A=b'86061000870018B106160000F8\r\n'
FRAME_B=b'86071000870018B106170000F6\r\n'
OPAQUE_FACE=b'86061000870018B10616FACE30\r\n'
WRONG_SOURCE=b'86091000870018B106160000F5\r\n'
WRONG_SERIAL=b'86061000870018B10699000075\r\n'
BARE=b'870018B10616000094\r\n'


def parse(data,**options):
    return decode_serial_address_receipt(data,**(dict(serial=A,destination=6,local_unit=16)|options))


def literal_frame(payload):
    """Independent test-only checksum builder for non-native malformed variants."""
    data=bytes.fromhex(payload)
    check=(256-(sum(data)%256))%256
    return (payload+format(check,'02X')).encode()+b'\r\n'


class SelectedSerialCodecTests(unittest.TestCase):
    def test_exact_native_requests_and_separate_srchk(self):
        self.assertEqual(encode_serial_address(A,6),b'\\05FF000F0018B106160615g\r')
        self.assertEqual(encode_serial_address(B,7),b'\\05FF000F0018B106170713g\r')
        self.assertEqual(encode_serial_address(A,6,command_checksum=True),b'\\05FF000F0018B106160615EDg\r')
        self.assertEqual(encode_serial_address(B,7,command_checksum=True,confirmation=b'z'),
                         b'\\05FF000F0018B106170713EDz\r')

    def test_independent_twenty_twelve_bit_boundaries_and_decimal_normalization(self):
        self.assertEqual(encode_serial_address('0.1',2),b'\\05FF000F000000000102FDg\r')
        self.assertEqual(encode_serial_address('1.0',2),b'\\05FF000F000000100002EEg\r')
        self.assertEqual(encode_serial_address('1048575.4094',254),b'\\05FF000F00FFFFFFFEFE07g\r')
        self.assertEqual(encode_serial_address('0101136.01558',6),encode_serial_address(A,6))

    def test_inner_checksum_scope_excludes_header_and_outer_checksum_covers_both(self):
        for serial,target in ((A,6),(B,7),('0.1',2),('1048575.4094',254)):
            with self.subTest(serial=serial,target=target):
                ordinary=bytes.fromhex(encode_serial_address(serial,target)[1:-2].decode())
                srchk=bytes.fromhex(encode_serial_address(serial,target,command_checksum=True)[1:-2].decode())
                self.assertEqual(len(ordinary),11);self.assertEqual(ordinary[:5],bytes.fromhex('05FF000F00'))
                self.assertEqual(sum(ordinary[4:])%256,0)
                self.assertEqual(sum(ordinary)%256,0x13)
                self.assertEqual(srchk,ordinary+b'\xed');self.assertEqual(sum(srchk)%256,0)

    def test_invalid_or_unknown_serials_rejected_without_wrapping(self):
        for serial in (None,1,True,b'101136.1558','',A+' ',' '+A,'+1.2','-1.2','1.-2','1.2.3',
                       '1','1.','1.4096','1048576.1','0.0','1048575.4095','１.２','0x18B10616',
                       '9'*100+'.1'):
            with self.subTest(serial=serial),self.assertRaises(ValueError):encode_serial_address(serial,6)

    def test_destination_confirmation_and_checksum_validation(self):
        for destination in (None,False,True,6.,'6',-1,0,1,255,256):
            with self.subTest(destination=destination),self.assertRaises(ValueError):encode_serial_address(A,destination)
        for confirmation in (None,'g',b'',b'gg',b'f',b'{',b'G',bytearray(b'g'),b'g\r'):
            with self.subTest(confirmation=confirmation),self.assertRaises(ValueError):
                encode_serial_address(A,6,confirmation=confirmation)
        for checksum in (None,0,1,'yes',[],object()):
            with self.subTest(checksum=checksum),self.assertRaises(ValueError):
                encode_serial_address(A,6,command_checksum=checksum)

    def test_native_receipts_only_establish_correlation(self):
        for serial,destination,frame in ((A,6,FRAME_A),(B,7,FRAME_B)):
            with self.subTest(serial=serial):
                receipt=parse(b'g.'+frame,serial=serial,destination=destination)
                self.assertEqual(receipt.status,'matched');self.assertTrue(receipt.matched)
                self.assertFalse(receipt.movement_verified);self.assertFalse(receipt.persistence_verified)
                reply=receipt.replies[0]
                self.assertEqual((reply.header,reply.source,reply.destination,reply.route),(0x86,destination,16,b'\0'))
                self.assertEqual(reply.serial,serial);self.assertTrue(reply.serial_known)
                self.assertEqual(reply.opaque_tail,b'\0\0')
                document=json.loads(json.dumps(receipt.as_dict()))
                self.assertTrue(document['receipt_matches_request'])
                self.assertFalse(document['movement_verified']);self.assertFalse(document['persistence_verified'])
                self.assertTrue(document['requires_independent_verification']);self.assertFalse(document['io_performed'])
                self.assertEqual(document['raw_hex'],(b'g.'+frame).hex())

    def test_native_opaque_tail_is_retained_without_success_or_persistence_meaning(self):
        receipt=parse(b'g.'+OPAQUE_FACE)
        self.assertTrue(receipt.matched);self.assertEqual(receipt.replies[0].opaque_tail,b'\xfa\xce')
        self.assertFalse(receipt.as_dict()['replies'][0]['opaque_tail_interpreted'])
        self.assertFalse(receipt.movement_verified)
        # The native forged-success/no-move fault used exactly FRAME_A too.
        self.assertFalse(parse(b'g.'+FRAME_A).movement_verified)

    def test_missing_confirmation_keeps_structural_reply_but_cannot_match(self):
        receipt=parse(FRAME_A)
        self.assertEqual(receipt.status,'unverified');self.assertFalse(receipt.matched)
        self.assertEqual(receipt.issues,('missing_confirmation',));self.assertEqual(receipt.replies[0].serial,A)

    def test_bare_native_receipt_is_unattributed(self):
        receipt=parse(b'g.'+BARE)
        self.assertEqual(receipt.status,'unverified');self.assertIn('bare_receipt_unattributed',receipt.issues)
        self.assertIsNone(receipt.replies[0].source);self.assertIsNone(receipt.replies[0].destination)
        self.assertEqual(receipt.replies[0].serial,A);self.assertFalse(receipt.matched)

    def test_native_wrong_source_serial_and_independent_wrong_local_route_fail_correlation(self):
        cases=((WRONG_SOURCE,'source_mismatch'),(WRONG_SERIAL,'serial_mismatch'),
               (literal_frame('86061100870018B106160000'),'local_destination_mismatch'),
               (literal_frame('8606100100870018B106160000'),'route_mismatch'))
        for frame,issue in cases:
            with self.subTest(issue=issue):
                receipt=parse(b'g.'+frame)
                self.assertEqual(receipt.status,'unverified');self.assertIn(issue,receipt.issues)
                self.assertFalse(receipt.matched);self.assertEqual(len(receipt.replies),1)

    def test_unknown_serials_and_unsupported_headers_remain_unverified(self):
        for payload,issue in (('860610008700000000000000','unknown_serial'),
                              ('860610008700FFFFFFFF0000','unknown_serial'),
                              ('06061000870018B106160000','unsupported_receipt_header'),
                              ('C6061000870018B106160000','unsupported_receipt_header')):
            with self.subTest(payload=payload):
                receipt=parse(b'g.'+literal_frame(payload))
                self.assertEqual(receipt.status,'unverified');self.assertIn(issue,receipt.issues)

    def test_wrong_cal_prefix_length_or_operation_cannot_match(self):
        for payload in ('86061000870118B106160000','86061000860018B1061600',
                        '86061000880018B10616000000','8606100032204E'):
            with self.subTest(payload=payload):
                receipt=parse(b'g.'+literal_frame(payload))
                self.assertEqual(receipt.status,'unverified');self.assertIn('unsupported_receipt_cal',receipt.issues)
                self.assertEqual(receipt.replies,());self.assertFalse(receipt.matched)

    def test_multiple_cals_frames_confirmations_and_order_are_ambiguous(self):
        for data,issue in ((b'g.'+FRAME_A+FRAME_A,'multiple_frames'),
                           (b'g.'+FRAME_A+WRONG_SOURCE,'multiple_frames'),
                           (b'g.g.'+FRAME_A,'multiple_confirmations'),
                           (b'h.'+FRAME_A,'foreign_confirmation'),
                           (FRAME_A+b'g.','receipt_before_confirmation'),
                           (b'g.'+literal_frame('86061000870018B10616000032204E'),'multiple_cals'),
                           (b'g.+'+FRAME_A,'unsolicited_notification')):
            with self.subTest(issue=issue,data=data):
                receipt=parse(data)
                self.assertEqual(receipt.status,'ambiguous');self.assertIn(issue,receipt.issues)
                self.assertFalse(receipt.matched)

    def test_rejected_confirmation_is_not_success_even_with_a_matching_frame(self):
        for code in (b'#',b'$',b'%',b'!',):
            with self.subTest(code=code):
                receipt=parse(b'g'+code)
                self.assertEqual(receipt.status,'rejected');self.assertFalse(receipt.matched)
                contradicted=parse(b'g'+code+FRAME_A)
                self.assertEqual(contradicted.status,'ambiguous')
                self.assertIn('receipt_after_rejection',contradicted.issues)

    def test_empty_confirmation_only_and_truncated_capture_are_incomplete(self):
        for data in (b'',b'g',b'g.',b'g.86',b'g.'+FRAME_A.rstrip(b'\r\n'),b'g.'+FRAME_A+b'h',
                     b'g.'+FRAME_A+b'86'):
            with self.subTest(data=data):
                receipt=parse(data)
                self.assertEqual(receipt.status,'incomplete');self.assertFalse(receipt.matched)
                if data.endswith((b'h',b'86')):self.assertTrue(receipt.pending)

    def test_invalid_checksum_hex_command_prefix_and_cal_framing_are_invalid(self):
        cases=(b'g.'+FRAME_A.replace(b'F8',b'F9'),b'g.860\r\n',b'g.XX\r\n',b'g?'+FRAME_A,
               b'g.\\'+FRAME_A,b'g.'+literal_frame('86061000870018B10616'),
               b'g.'+literal_frame('8606100900870018B106160000'))
        for data in cases:
            with self.subTest(data=data):
                receipt=parse(data)
                self.assertEqual(receipt.status,'invalid');self.assertFalse(receipt.matched);self.assertTrue(receipt.errors)

    def test_valid_prefix_does_not_hide_malformed_or_partial_trailing_bytes(self):
        for suffix,status in ((b'XX\r\n','invalid'),(b'g?','invalid'),(b'8','incomplete'),
                              (FRAME_B,'ambiguous'),(b'g.','ambiguous')):
            with self.subTest(suffix=suffix):
                data=b'g.'+FRAME_A+suffix;receipt=parse(data)
                self.assertEqual(receipt.status,status);self.assertFalse(receipt.matched)
                self.assertEqual(receipt.replies[0].serial,A);self.assertEqual(receipt.raw,data)

    def test_case_flow_control_and_line_endings_preserve_original_capture(self):
        raw=b'\r\ng\x11.\x13'+FRAME_A.lower()+b'\r\n'
        receipt=parse(raw)
        self.assertTrue(receipt.matched);self.assertEqual(receipt.raw,raw)
        self.assertEqual(receipt.replies[0].packed_serial,bytes.fromhex('18B10616'))
        self.assertTrue(parse(b'z.'+FRAME_A,confirmation=b'z').matched)

    def test_parser_input_bounds_and_argument_validation(self):
        for data in ('g.'+FRAME_A.decode(),None,42):
            with self.subTest(data=data),self.assertRaises(TypeError):parse(data)
        with self.assertRaises(ValueError):parse(b'0'*4097)
        for options in ({'serial':'0.0'},{'destination':True},{'destination':255},
                        {'local_unit':True},{'local_unit':-1},{'local_unit':256},{'confirmation':b'gg'}):
            with self.subTest(options=options),self.assertRaises(ValueError):parse(b'g.'+FRAME_A,**options)
        buffer=bytearray(b'g.'+FRAME_A);receipt=parse(buffer);buffer.clear()
        self.assertEqual(receipt.raw,b'g.'+FRAME_A)
        self.assertTrue(parse(memoryview(b'g.'+FRAME_A)).matched)

    def test_codec_and_parser_perform_no_io(self):
        with patch('socket.socket',side_effect=AssertionError('No socket permitted')), \
                patch('builtins.open',side_effect=AssertionError('No file I/O permitted')):
            self.assertEqual(encode_serial_address(A,6),b'\\05FF000F0018B106160615g\r')
            self.assertTrue(parse(b'g.'+FRAME_A).matched)


if __name__=='__main__':unittest.main()
