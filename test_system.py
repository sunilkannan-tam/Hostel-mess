import os
os.environ["DATABASE_URL"]="sqlite:///./test_mess.db"
os.environ["STAFF_USERNAME"]="testadmin"
os.environ["STAFF_PASSWORD"]="testpass123"
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client=TestClient(app)
AUTH=('testadmin','testpass123')

def test_end_to_end_reserve_tap_confirm_billing():
    s1=client.post('/api/students',json={'name':'Arun','roll_number':'CE001','room_number':'101','rfid_uid':'RFID-A','photo_url':'https://example.com/arun.jpg'}).json()
    s2=client.post('/api/students',json={'name':'Bala','roll_number':'CE002','room_number':'102','rfid_uid':'RFID-B'}).json()
    meal=client.post('/api/meals',json={'meal_date':'2026-09-03','meal_type':'lunch','menu':'Rice, sambar','actual_cost':'100'}).json()
    assert client.post('/api/reservations',json={'student_id':s1['id'],'meal_id':meal['id'],'reserve':True}).status_code==200
    assert client.post('/api/reservations',json={'student_id':s2['id'],'meal_id':meal['id'],'reserve':True}).status_code==200
    tap=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-A','photo_url':'https://example.com/arun.jpg','meal_id':meal['id']})
    assert tap.status_code==200
    assert client.post('/api/serve/confirm',json={'collection_id':tap.json()['collection_id'],'staff_id':'staff'}).status_code==200
    tap2=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-B','meal_id':meal['id']})
    assert tap2.status_code==200
    out=client.post('/api/serve/confirm',json={'collection_id':tap2.json()['collection_id'],'staff_id':'staff'}).json()
    assert out['status']=='served'
    assert out['charge']=='50.00'
    assert client.get(f"/api/students/{s1['id']}/ledger").json()['balance']=='50.00'
    assert client.get(f"/api/students/{s2['id']}/ledger").json()['balance']=='50.00'

def test_no_reservation_denied():
    meal=client.post('/api/meals',json={'meal_date':'2026-09-04','meal_type':'breakfast','actual_cost':'50'}).json()
    s=client.post('/api/students',json={'name':'Cathy','roll_number':'CE003','rfid_uid':'RFID-C'}).json()
    r=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-C','meal_id':meal['id']})
    assert r.status_code==403

def test_duplicate_tap_denied():
    s=client.post('/api/students',json={'name':'Dev','roll_number':'CE004','rfid_uid':'RFID-D'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-05','meal_type':'dinner','actual_cost':'40'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    assert client.post('/api/rfid/tap',json={'rfid_uid':'RFID-D','meal_id':m['id']}).status_code==200
    assert client.post('/api/rfid/tap',json={'rfid_uid':'RFID-D','meal_id':m['id']}).status_code==409

def test_tap_without_serving_is_not_billed():
    s=client.post('/api/students',json={'name':'Esha','roll_number':'CE005','rfid_uid':'RFID-E'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-06','meal_type':'lunch','actual_cost':'60'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    tap=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-E','meal_id':m['id']}).json()
    assert client.post('/api/serve/reject',params={'collection_id':tap['collection_id']}).status_code==200
    assert client.get(f"/api/students/{s['id']}/ledger").json()['balance']=='0.00'


def test_rfid_response_includes_photo_and_serving_counter():
    s=client.post('/api/students',json={'name':'Photo Student','roll_number':'CE100','rfid_uid':'RFID-P','photo_url':'https://example.com/photo.jpg'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-07','meal_type':'breakfast','actual_cost':'30'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    tap=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-P','meal_id':m['id']})
    assert tap.status_code==200
    data=tap.json()
    assert data['student']['photo_url']=='https://example.com/photo.jpg'
    assert data['verification']['photo_check_required'] is True
    pending=client.get('/api/serving-counter/pending').json()
    assert any(x['collection_id']==data['collection_id'] for x in pending)

def test_rejected_serving_has_no_charge():
    s=client.post('/api/students',json={'name':'Reject Student','roll_number':'CE101','rfid_uid':'RFID-R'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-08','meal_type':'dinner','actual_cost':'45'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    tap=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-R','meal_id':m['id']}).json()
    out=client.post('/api/serve/reject',params={'collection_id':tap['collection_id']})
    assert out.status_code==200
    assert client.get(f"/api/students/{s['id']}/ledger").json()['balance']=='0.00'

# --- New tests for the tier-2 / low-infrastructure hardening pass -------

def test_dashboard_and_serving_counter_require_staff_auth():
    assert client.get('/dashboard').status_code == 401
    assert client.get('/dashboard', auth=AUTH).status_code == 200
    assert client.get('/serving-counter').status_code == 401
    assert client.get('/serving-counter', auth=AUTH).status_code == 200

def test_student_update_reissues_rfid_card_and_deactivates():
    s=client.post('/api/students',json={'name':'Farah','roll_number':'CE200','rfid_uid':'RFID-OLD'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-09','meal_type':'lunch','actual_cost':'20'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    # unauthenticated update is rejected
    assert client.patch(f"/api/students/{s['id']}",json={'rfid_uid':'RFID-NEW'}).status_code == 401
    upd=client.patch(f"/api/students/{s['id']}",json={'rfid_uid':'RFID-NEW'},auth=AUTH)
    assert upd.status_code==200 and upd.json()['rfid_uid']=='RFID-NEW'
    # the old, now-unassigned card no longer works
    assert client.post('/api/rfid/tap',json={'rfid_uid':'RFID-OLD','meal_id':m['id']}).status_code==404
    assert client.post('/api/rfid/tap',json={'rfid_uid':'RFID-NEW','meal_id':m['id']}).status_code==200
    deact=client.patch(f"/api/students/{s['id']}",json={'active':False},auth=AUTH)
    assert deact.status_code==200 and deact.json()['active'] is False

def test_student_update_rejects_rfid_uid_already_in_use():
    a=client.post('/api/students',json={'name':'Ivy','roll_number':'CE210','rfid_uid':'RFID-IVY'}).json()
    client.post('/api/students',json={'name':'Jai','roll_number':'CE211','rfid_uid':'RFID-JAI'})
    clash=client.patch(f"/api/students/{a['id']}",json={'rfid_uid':'RFID-JAI'},auth=AUTH)
    assert clash.status_code==409

def test_meal_update_late_cost_entry_recalculates_already_served_charges():
    s1=client.post('/api/students',json={'name':'Gita','roll_number':'CE201','rfid_uid':'RFID-G'}).json()
    s2=client.post('/api/students',json={'name':'Hari','roll_number':'CE202','rfid_uid':'RFID-H'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-10','meal_type':'dinner'}).json()  # no actual_cost yet
    client.post('/api/reservations',json={'student_id':s1['id'],'meal_id':m['id'],'reserve':True})
    client.post('/api/reservations',json={'student_id':s2['id'],'meal_id':m['id'],'reserve':True})
    for rfid in ('RFID-G','RFID-H'):
        tap=client.post('/api/rfid/tap',json={'rfid_uid':rfid,'meal_id':m['id']}).json()
        client.post('/api/serve/confirm',json={'collection_id':tap['collection_id']})
    assert client.get(f"/api/students/{s1['id']}/ledger").json()['balance']=='0.00'
    assert client.patch(f"/api/meals/{m['id']}",json={'actual_cost':'80'}).status_code==401
    upd=client.patch(f"/api/meals/{m['id']}",json={'actual_cost':'80'},auth=AUTH)
    assert upd.status_code==200
    assert client.get(f"/api/students/{s1['id']}/ledger").json()['balance']=='40.00'
    assert client.get(f"/api/students/{s2['id']}/ledger").json()['balance']=='40.00'

def test_close_meal_applies_default_rate_when_cost_never_entered():
    os.environ["DEFAULT_MEAL_RATE"]="40.00"
    try:
        s=client.post('/api/students',json={'name':'Kabir','roll_number':'CE220','rfid_uid':'RFID-K'}).json()
        m=client.post('/api/meals',json={'meal_date':'2026-09-11','meal_type':'breakfast'}).json()
        client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
        tap=client.post('/api/rfid/tap',json={'rfid_uid':'RFID-K','meal_id':m['id']}).json()
        client.post('/api/serve/confirm',json={'collection_id':tap['collection_id']})
        assert client.get(f"/api/students/{s['id']}/ledger").json()['balance']=='0.00'
        closed=client.post(f"/api/meals/{m['id']}/close",auth=AUTH)
        assert closed.status_code==200
        assert 'note' in closed.json()
        assert client.get(f"/api/students/{s['id']}/ledger").json()['balance']=='40.00'
    finally:
        del os.environ["DEFAULT_MEAL_RATE"]

def test_manual_csv_import_reconciles_paper_attendance():
    s=client.post('/api/students',json={'name':'Leela','roll_number':'CE230','rfid_uid':'RFID-L'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-12','meal_type':'lunch','actual_cost':'30'}).json()
    client.post('/api/reservations',json={'student_id':s['id'],'meal_id':m['id'],'reserve':True})
    csv_body=f"roll_number,meal_id,status\nCE230,{m['id']},served\nUNKNOWN,{m['id']},served\n"
    files={'file':('paper.csv',csv_body,'text/csv')}
    assert client.post('/api/collections/import',files=files).status_code==401
    res=client.post('/api/collections/import',files=files,auth=AUTH)
    assert res.status_code==200
    body=res.json()
    assert body['created']==1 and len(body['errors'])==1
    assert client.get(f"/api/students/{s['id']}/ledger").json()['balance']=='30.00'
    # re-importing the same row is skipped, not double-billed
    res2=client.post('/api/collections/import',files={'file':('paper.csv',csv_body,'text/csv')},auth=AUTH)
    assert res2.json()['skipped_existing']==1

def test_reserve_page_loads_and_accepts_submission():
    s=client.post('/api/students',json={'name':'Meera','roll_number':'CE240','rfid_uid':'RFID-M'}).json()
    m=client.post('/api/meals',json={'meal_date':'2026-09-13','meal_type':'dinner','actual_cost':'25'}).json()
    assert client.get('/reserve').status_code==200
    sub=client.post(f"/reserve/{m['id']}",data={'roll_number':'CE240','reserve':'yes'})
    assert sub.status_code==200
    assert client.post('/api/rfid/tap',json={'rfid_uid':'RFID-M','meal_id':m['id']}).status_code==200
