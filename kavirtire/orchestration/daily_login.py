"""Date-bound automatic login using Tehran civil time, independent of host TZ."""
import asyncio

from kavirtire.orchestration.scheduling import in_tehran

class DailyLogin:
    def __init__(self, controller):
        self.controller = controller
        self.admissions = controller.daily_admissions

    async def tick(self):
        controller = self.controller
        now = in_tehran(controller.clock.now())
        schedule = controller.settings.schedule
        if (controller._closing or controller.automatic_suppressed_date == now.date()
                or now < schedule.at(now.date(), schedule.login)
                or now >= schedule.cutoff(now.date())):
            return
        if not controller.profile.national_id():
            return
        # The process/profile locks cover this journal and the single worker.
        # A running manual daily arm consumes today's automatic slot as well.
        if controller.active and controller.status().inventory_test:
            return
        if not self.admissions.claim(now.date()):
            return
        if controller.active:
            return
        receipt = await controller.arm(controller.owner)
        if receipt.accepted:
            await controller._notify('automatic_login_started')
        else:
            controller.diagnostics.event('automatic_login_refused', reason=receipt.reason)
            await controller._notify(receipt.reason)

    async def run(self):
        failed = False
        while not self.controller._closing:
            try:
                await self.tick()
                failed = False
            except Exception as error:
                if not failed:
                    self.controller.diagnostics.error('daily_login', error)
                    await self.controller._notify('automatic_login_failed')
                failed = True
            # Real elapsed waiting; decisions always re-read Tehran time.
            await asyncio.sleep(1)
