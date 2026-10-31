import unittest
from ventureos.gateways import Principal, ModelGateway, ModelReply, ToolGateway

class GatewayTests(unittest.TestCase):
    def test_model_authorization_precedes_provider(self):
        calls = []
        gateway = ModelGateway(lambda model, prompt, **kw: calls.append(prompt) or ModelReply('ok', 2))
        allowed = Principal('a', frozenset({'model:small', 'tool:lookup'}))
        self.assertEqual(gateway.generate(allowed, 'a', 'small', 'hello', 3).units, 2)
        for tenant, model in [('b', 'small'), ('a', 'large')]:
            with self.assertRaises(PermissionError):
                gateway.generate(allowed, tenant, model, 'secret', 3)
        self.assertEqual(len(calls), 1)

    def test_tool_scoped_and_side_effects_default_denied(self):
        gateway = ToolGateway()
        gateway.register('lookup', lambda args: args, side_effect=False)
        gateway.register('send', lambda args: args, side_effect=True)
        actor = Principal('a', frozenset({'tool:lookup', 'tool:send'}))
        self.assertEqual(gateway.invoke(actor, 'a', 'lookup', {'id': 1}), {'id': 1})
        with self.assertRaises(PermissionError):
            gateway.invoke(actor, 'b', 'lookup', {})
        with self.assertRaises(PermissionError):
            gateway.invoke(actor, 'a', 'send', {})

    def test_provider_contract(self):
        actor = Principal('a', frozenset({'model:m'}))
        with self.assertRaises(ValueError):
            ModelGateway(lambda m,p,**kw: ModelReply('bad', -1)).generate(actor,'a','m','p',5)
