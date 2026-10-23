"""Tenant configuration, encrypted credentials and existing-runtime resolution."""
import base64
from uuid import UUID, uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from budbot.core.tenancy import TenantContext
from budbot.models.provider import BusinessAIProfile, ProviderCredential
from budbot.models.auth import AuditEvent
from budbot.models.business import Business
from budbot.models.user import BusinessMembership
from budbot.providers.ai.errors import AIError
from budbot.services.provider_service import ProviderService
from budbot.services.secret_store import EncryptedSecretStore, SecretStoreError
from budbot.schemas.provider import CredentialUpdate

KEY = SecretStr(base64.urlsafe_b64encode(bytes(range(32))).decode())
SECRET = "synthetic-provider-credential-only"

@pytest.fixture
async def provider_admin(m2_client, application, db_session):
    application.state.settings.provider_root_key = KEY
    application.state.settings.ai_compatible_endpoints = ("http://host.docker.internal:1234/v1", "http://127.0.0.1:1234/v1")
    me = (await m2_client.get('/api/v1/auth/me')).json()
    m2_client.headers['X-CSRF-Token'] = me['csrf_token']
    bid = me['businesses'][0]['business_id']
    return m2_client, db_session, application.state.settings, bid, f'/api/v1/businesses/{bid}/provider'

async def config(client, path, provider='openrouter', **extra):
    return await client.put(path, json={'provider':provider, 'model':'test-model', 'base_url':'http://host.docker.internal:1234/v1' if provider=='openai_compatible' else None, **extra})

async def test_encryption_and_runtime_for_every_provider(provider_admin):
    client, db, settings, bid, path = provider_admin
    for provider, transport, harness in [('openrouter','openai_compatible','generic_openai'), ('openai','openai','openai_chat'), ('anthropic','anthropic','anthropic_native'), ('openai_compatible','openai_compatible','generic_openai')]:
        assert (await config(client,path,provider)).status_code == 200
        first = await client.put(path+'/credential',json={'credential':SECRET})
        assert first.status_code == 200, first.text
        assert first.json()['credential_configured']
        row = await db.get(ProviderCredential,UUID(bid))
        encrypted = row.encrypted_value
        assert SECRET.encode() not in encrypted
        assert SECRET not in first.text and base64.b64encode(encrypted).decode() not in first.text
        assert (await config(client,path,provider,enabled=True,tool_calling=True)).status_code == 200
        runtime = await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
        assert (runtime.provider,runtime.harness,runtime.api_key)==(transport,harness,SECRET)
        assert SECRET not in repr(runtime)
        if provider=='openrouter': assert runtime.base_url=='https://openrouter.ai/api/v1'
        assert (await config(client,path,provider,enabled=True,model='another-model')).status_code == 200
        await db.refresh(row)
        assert row.encrypted_value == encrypted
        await client.put(path+'/credential',json={'credential':SECRET})
        await db.refresh(row)
        assert row.encrypted_value != encrypted
        assert (await config(client,path,'openai' if provider!='openai' else 'anthropic')).status_code == 409
        removed=await client.delete(path+'/credential')
        assert removed.status_code==200 and not removed.json()['enabled'] and not removed.json()['credential_configured']
    history=(await client.get(path.replace('/provider','/audit'))).text
    assert SECRET not in history and 'encrypted_value' not in history
    assert all(action in history for action in ('credential_set','credential_replaced','credential_removed','configuration_updated'))

@pytest.mark.parametrize('provider',['openrouter','openai','anthropic'])
async def test_required_credentials(provider_admin,provider):
    client,db,settings,bid,path=provider_admin
    assert (await config(client,path,provider,enabled=True)).status_code==409
    assert (await config(client,path,provider)).status_code==200
    with pytest.raises(AIError): await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()

@pytest.mark.parametrize('url',['ftp://host','http://u:p@host/v1','https://host/v1?key=private','https://host/#private','http:///empty','http://[bad'])
async def test_bad_url_does_not_echo_rejected_input(provider_admin,url):
    client,db,settings,bid,path=provider_admin
    result=await config(client,path,'openai_compatible',base_url=url)
    assert result.status_code==422 and 'private' not in result.text and 'input' not in result.json()['detail'][0]

async def test_local_optional_key_and_fail_closed_fallback(provider_admin):
    client,db,settings,bid,path=provider_admin
    assert (await config(client,path,'openai_compatible',enabled=True)).status_code==200
    assert (await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()).api_key is None
    other=Business(display_name='Other',industry='general_retail');db.add(other);await db.commit()
    strict=settings.model_copy(update={'environment':'production','ai_enabled':True,'ai_model':'global','ai_api_key':SecretStr(SECRET)})
    with pytest.raises(AIError): await ProviderService(db,TenantContext(other.id),strict).runtime()
    strict.ai_legacy_business_id=UUID(bid)
    with pytest.raises(AIError): await ProviderService(db,TenantContext(other.id),strict).runtime()

@pytest.mark.parametrize('role',['admin','manager','viewer'])
async def test_permissions_and_cross_tenant(provider_admin,role):
    client,db,settings,bid,path=provider_admin
    assert (await config(client,path)).status_code==200
    foreign=Business(display_name='Foreign',industry='general_retail');db.add(foreign);await db.commit()
    foreign_path=f'/api/v1/businesses/{foreign.id}/provider'
    for method,suffix,payload in [('GET','',None),('PUT','',{'provider':'openai','model':'x'}),('PUT','/credential',{'credential':SECRET}),('DELETE','/credential',None)]:
        assert (await client.request(method,foreign_path+suffix,json=payload,headers={'X-BudBot-Business-ID':bid})).status_code==404
    member=await db.scalar(select(BusinessMembership).where(BusinessMembership.business_id==UUID(bid)));member.role=role;await db.commit()
    assert (await client.get(path)).status_code==403
    assert (await config(client,path)).status_code==403
    assert (await client.put(path+'/credential',json={'credential':SECRET})).status_code==403
    assert (await client.delete(path+'/credential')).status_code==403

async def test_csrf_auth_and_safe_secret_failure(provider_admin):
    client,db,settings,bid,path=provider_admin
    await config(client,path)
    settings.provider_root_key=None
    response=await client.put(path+'/credential',json={'credential':SECRET})
    assert response.status_code==503 and SECRET not in response.text
    assert await db.get(ProviderCredential,UUID(bid)) is None
    assert len((await db.scalars(select(AuditEvent).where(AuditEvent.business_id==UUID(bid)))).all())==1
    settings.provider_root_key=KEY
    invalid=await client.put(path+'/credential',json={'credential':SECRET+'\n'})
    assert invalid.status_code==422 and SECRET not in invalid.text
    client.headers.pop('X-CSRF-Token')
    assert (await config(client,path)).status_code==403
    assert (await client.put(path+'/credential',json={'credential':SECRET})).status_code==403
    assert (await client.delete(path+'/credential')).status_code==403
    client.cookies.clear()
    assert (await client.get(path,headers={'X-BudBot-Business-ID':bid})).status_code==401

async def test_runtime_ciphertext_tenant_binding_and_corruption(provider_admin):
    client,db,settings,bid,path=provider_admin
    await config(client,path);await client.put(path+'/credential',json={'credential':SECRET});await config(client,path,enabled=True)
    row=await db.get(ProviderCredential,UUID(bid))
    store=EncryptedSecretStore(KEY)
    assert store.open(UUID(bid),'openrouter',row.version,row.encrypted_value).get_secret_value()==SECRET
    for tenant,provider,version,value in [(uuid4(),'openrouter',row.version,row.encrypted_value),(UUID(bid),'openai',row.version,row.encrypted_value),(UUID(bid),'openrouter','future',row.encrypted_value),(UUID(bid),'openrouter',row.version,b'broken')]:
        with pytest.raises(SecretStoreError) as exc: store.open(tenant,provider,version,value)
        assert SECRET not in str(exc.value)
    settings.provider_root_key=SecretStr(base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode())
    with pytest.raises(AIError) as exc: await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
    assert exc.value.code=='AI_CONFIGURATION_INVALID'
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(CredentialUpdate(credential=SECRET))
    assert CredentialUpdate(credential=SECRET).model_dump()=={}

async def test_endpoint_policy_and_credential_destination_binding(provider_admin):
    client,db,settings,bid,path=provider_admin
    assert (await config(client,path,'openai_compatible',base_url='http://169.254.169.254/v1')).status_code==422
    assert (await config(client,path,'openai_compatible')).status_code==200
    await client.put(path+'/credential',json={'credential':SECRET})
    assert (await config(client,path,'openai_compatible',base_url='http://127.0.0.1:1234/v1')).status_code==409
    await config(client,path,'openai_compatible',enabled=True)
    profile=await db.get(BusinessAIProfile,UUID(bid));profile.base_url='http://127.0.0.1:1234/v1';await db.commit()
    with pytest.raises(AIError): await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
    settings.ai_tenant_enabled=False
    with pytest.raises(AIError) as exc: await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
    assert exc.value.code=='AI_DISABLED'

async def test_two_businesses_resolve_only_their_own_credentials(provider_admin):
    client,db,settings,bid,path=provider_admin
    await config(client,path);await client.put(path+'/credential',json={'credential':SECRET});await config(client,path,enabled=True)
    other=Business(display_name='Second tenant',industry='general_retail');db.add(other);await db.flush()
    db.add(BusinessAIProfile(business_id=other.id,provider='anthropic',model='other-model',enabled=True,tool_calling=True))
    version,value=EncryptedSecretStore(KEY).seal(other.id,'anthropic',SecretStr('synthetic-second-tenant-key'))
    db.add(ProviderCredential(business_id=other.id,version=version,encrypted_value=value));await db.commit()
    first=await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
    second=await ProviderService(db,TenantContext(other.id),settings).runtime()
    assert first.api_key==SECRET and second.api_key=='synthetic-second-tenant-key'
    row=await db.get(ProviderCredential,UUID(bid));row.encrypted_value=value;await db.commit()
    with pytest.raises(AIError): await ProviderService(db,TenantContext(UUID(bid)),settings).runtime()
