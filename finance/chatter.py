from chatter import register
from finance.models import CustomerInvoice, Expense
from utils.permissions import IsFinance, IsSalesOrFinanceOrSuper

register(CustomerInvoice, name="invoice", permission_classes=[IsSalesOrFinanceOrSuper])
register(Expense, permission_classes=[IsFinance])
