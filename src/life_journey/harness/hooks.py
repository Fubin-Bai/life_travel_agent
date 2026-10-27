"""只观察脱敏快照的轻量hooks；不允许hook改写业务输入输出。"""

class HarnessHook:
    """默认no-op，critical必须显式声明；多个实例按注册顺序执行。"""
    critical=False
    def before_run(self,context,event):pass
    def after_run(self,context,event):pass
    def before_model(self,context,event):pass
    def after_model(self,context,event):pass
    def before_tool(self,context,event):pass
    def after_tool(self,context,event):pass
    def before_memory_retrieval(self,context,event):pass
    def after_memory_retrieval(self,context,event):pass
    def before_validate(self,context,event):pass
    def after_validate(self,context,event):pass
    def before_replan(self,context,event):pass
    def after_replan(self,context,event):pass
