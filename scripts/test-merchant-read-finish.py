import sys,unittest,copy
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from python.merchant_chat import finish_read,OFFLINE
class Store:
 def __init__(self):
  self.db={'conversations':{'c':{'conversationId':'c','active':True,'messages':[{'text':'free invoice','evidenceId':'proof'}]}},'inquiries':{},'outbox':{}}
  self.saved=0
 def get(self,table,key):return self.db[table][key]
 def save(self):self.saved+=1
class CompletionTests(unittest.TestCase):
 def setUp(self):self.s=Store();self.c=SimpleNamespace(args={'conversationId':'c','userReference':'user authorized completed read'})
 def test_read_completion_preserves_evidence_and_no_browser_dependency(self):
  before=copy.deepcopy(self.s.db['conversations']['c']['messages']);result=finish_read(self.c,self.s)
  self.assertFalse(self.s.db['conversations']['c']['active']);self.assertEqual(before,self.s.db['conversations']['c']['messages']);self.assertFalse(result['browserChanged']);self.assertFalse(result['messageSent']);self.assertIn('finish_merchant_read',OFFLINE)
 def test_active_inquiry_cannot_release(self):
  self.s.db['inquiries']['i']={'conversationId':'c','status':'active'}
  with self.assertRaisesRegex(RuntimeError,'CHAT_INQUIRY_ACTIVE'):finish_read(self.c,self.s)
  self.assertTrue(self.s.db['conversations']['c']['active']);self.assertEqual(self.s.saved,0)
 def test_both_uncertain_send_states_stay_protected(self):
  for status in ['dispatching','sent_unconfirmed']:
   self.s.db['outbox']['o']={'conversationId':'c','status':status}
   with self.assertRaisesRegex(RuntimeError,'CHAT_SEND_UNCONFIRMED'):finish_read(self.c,self.s)
   self.assertTrue(self.s.db['conversations']['c']['active']);self.assertEqual(self.s.saved,0)
 def test_missing_task_reference_rejected(self):
  self.c.args.pop('userReference')
  with self.assertRaises(ValueError):finish_read(self.c,self.s)
  self.assertEqual(self.s.saved,0)
if __name__=='__main__':unittest.main(verbosity=2)
