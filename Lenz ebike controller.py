from machine import Pin, PWM, ADC, I2C, Timer, UART
import time
import math

# Hardware Constants
THROTTLE_PIN = 34
BRAKE_FRONT_PIN = 12
BRAKE_REAR_PIN = 13
CADENCE_PIN = 14
TORQUE_PIN = 36
BATTERY_PIN = 35
MOTOR_TEMP_PIN = 32
CONTROLLER_TEMP_PIN = 33
CHARGING_PIN = 5
MOTOR_PWM_PIN = 15
UART_TX_PIN = 16
UART_RX_PIN = 17
HEADLIGHT_PIN = 25
TAILLIGHT_PIN = 26
HORN_PIN = 27
DISPLAY_SCL_PIN = 22
DISPLAY_SDA_PIN = 21

class EBikeController:
    def __init__(self):
        # Configuration
        self.motor_power = 500  # 250, 500, or 1000W
        self.max_current = self._calculate_max_current()
        self.max_speed = self._calculate_max_speed()
        self.wheel_circumference = 2.2  # meters
        
        # PID Control
        self.pid_kp = 0.8
        self.pid_ki = 0.05
        self.pid_kd = 0.1
        self.pid_integral = 0
        self.last_error = 0
        
        # Initialize hardware
        self._init_gpio()
        self._init_sensors()
        self._init_motor_control()
        self._init_display()
        
        # System state
        self.speed = 0.0
        self.cadence = 0
        self.torque = 0.0
        self.battery_level = 100
        self.voltage = 48.0
        self.motor_temp = 25.0
        self.controller_temp = 25.0
        self.motor_current = 0.0
        self.distance = 0.0
        self.assist_level = 2  # 1-3
        self.throttle_position = 0.0
        self.brake_active = False
        self.lights_on = False
        self.horn_active = False
        self.charging = False
        self.regen_active = False
        self.error_state = 0
        
        # Calibration values
        self.throttle_min = 200
        self.throttle_max = 3800
        self.torque_offset = 1800
        
        # Start timers
        self._start_timers()
        
        # Show startup screen
        self._show_startup_message()

    def _calculate_max_current(self):
        # Current limits based on motor power
        if self.motor_power == 250:
            return 10.0
        elif self.motor_power == 500:
            return 15.0
        else:  # 1000W
            return 25.0

    def _calculate_max_speed(self):
        # Speed limits based on motor power
        if self.motor_power == 250:
            return 25.0
        elif self.motor_power == 500:
            return 32.0
        else:  # 1000W
            return 45.0

    def _init_gpio(self):
        # Inputs
        self.throttle_adc = ADC(Pin(THROTTLE_PIN))
        self.throttle_adc.atten(ADC.ATTN_11DB)
        
        self.brake_front = Pin(BRAKE_FRONT_PIN, Pin.IN, Pin.PULL_UP)
        self.brake_rear = Pin(BRAKE_REAR_PIN, Pin.IN, Pin.PULL_UP)
        
        self.cadence_sensor = Pin(CADENCE_PIN, Pin.IN, Pin.PULL_UP)
        self.cadence_sensor.irq(trigger=Pin.IRQ_RISING, handler=self._cadence_interrupt)
        self.last_cadence_time = time.ticks_ms()
        self.cadence_pulses = 0
        
        # Outputs
        self.headlight = Pin(HEADLIGHT_PIN, Pin.OUT)
        self.taillight = Pin(TAILLIGHT_PIN, Pin.OUT)
        self.horn = Pin(HORN_PIN, Pin.OUT)
        
        # Motor control
        self.motor_pwm = PWM(Pin(MOTOR_PWM_PIN), freq=20000, duty=0)
        self.motor_uart = UART(1, baudrate=9600, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))

    def _init_sensors(self):
        self.torque_adc = ADC(Pin(TORQUE_PIN))
        self.torque_adc.atten(ADC.ATTN_11DB)
        
        self.battery_adc = ADC(Pin(BATTERY_PIN))
        self.battery_adc.atten(ADC.ATTN_11DB)
        
        self.motor_temp_adc = ADC(Pin(MOTOR_TEMP_PIN))
        self.motor_temp_adc.atten(ADC.ATTN_11DB)
        
        self.controller_temp_adc = ADC(Pin(CONTROLLER_TEMP_PIN))
        self.controller_temp_adc.atten(ADC.ATTN_11DB)
        
        self.charging_pin = Pin(CHARGING_PIN, Pin.IN, Pin.PULL_UP)

    def _init_motor_control(self):
        # Initialize motor control based on configuration
        self.motor_control_type = 'PWM'  # Can be 'PWM' or 'UART'
        self.motor_is_running = False

    def _init_display(self):
        self.i2c = I2C(0, scl=Pin(DISPLAY_SCL_PIN), sda=Pin(DISPLAY_SDA_PIN))
        self.display = SSD1306_I2C(128, 64, self.i2c)

    def _start_timers(self):
        # Main control loop (10ms)
        self.control_timer = Timer(0)
        self.control_timer.init(period=10, mode=Timer.PERIODIC, callback=self._control_loop)
        
        # Display update (100ms)
        self.display_timer = Timer(1)
        self.display_timer.init(period=100, mode=Timer.PERIODIC, callback=self._update_display)
        
        # Safety check (1s)
        self.safety_timer = Timer(2)
        self.safety_timer.init(period=1000, mode=Timer.PERIODIC, callback=self._safety_check)

    def _cadence_interrupt(self, pin):
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.last_cadence_time)
        if elapsed > 50:  # Debounce
            self.cadence_pulses += 1
            self.last_cadence_time = now

    def _show_startup_message(self):
        self.display.fill(0)
        self.display.text("eBike Controller", 0, 0)
        self.display.text(f"{self.motor_power}W System", 0, 16)
        self.display.text("Initializing...", 0, 32)
        self.display.show()
        time.sleep(2)

    def _control_loop(self, timer):
        # 1. Read all inputs
        self._read_sensors()
        
        # 2. Update system state
        self._update_state()
        
        # 3. Calculate motor output
        self._calculate_motor_output()
        
        # 4. Handle safety systems
        self._check_safety_limits()

    def _read_sensors(self):
        # Throttle position (0-100%)
        throttle_raw = self.throttle_adc.read()
        self.throttle_position = max(0, min(100, 
            (throttle_raw - self.throttle_min) / 
            (self.throttle_max - self.throttle_min) * 100
        ))
        
        # Brake status
        self.brake_active = not self.brake_front.value() or not self.brake_rear.value()
        
        # Cadence (RPM)
        now = time.ticks_ms()
        if now - self.last_cadence_time > 1000:  # No pulses for 1s = 0 RPM
            self.cadence = 0
        elif self.cadence_pulses > 0:
            elapsed = time.ticks_diff(now, self.last_cadence_time) / 1000  # seconds
            self.cadence = (self.cadence_pulses / 20) * (60 / elapsed)  # 20 pulses/rev
            self.cadence_pulses = 0
        
        # Torque (Nm)
        torque_raw = self.torque_adc.read() - self.torque_offset
        self.torque = torque_raw * 0.08  # Calibration factor
        
        # Battery voltage (through voltage divider)
        voltage_raw = self.battery_adc.read()
        self.voltage = (voltage_raw / 4095) * 3.3 * 5.7  # 1:5.7 divider
        
        # Battery level estimation
        if self.voltage > 54.6:  # 13S fully charged
            self.battery_level = 100
        elif self.voltage < 39.0:  # 13S empty
            self.battery_level = 0
        else:
            self.battery_level = int((self.voltage - 39.0) / (54.6 - 39.0) * 100)
        
        # Temperatures (simplified NTC reading)
        self.motor_temp = (self.motor_temp_adc.read() / 4095) * 100
        self.controller_temp = (self.controller_temp_adc.read() / 4095) * 100
        
        # Charging status
        self.charging = not self.charging_pin.value()

    def _update_state(self):
        # Calculate speed (km/h)
        self.speed = (self.cadence * self.wheel_circumference * 60) / 1000
        
        # Update distance (km)
        self.distance += (self.speed / 360000)  # 10ms in hours
        
        # Calculate motor power (W)
        self.motor_power = self.motor_current * self.voltage

    def _calculate_motor_output(self):
        if self.brake_active or self.battery_level < 5:
            # Emergency stop conditions
            target_current = 0
            self.regen_active = False
        else:
            # Normal operation
            target_current = self._calculate_target_current()
            
            # Apply field weakening at high speeds
            if self.speed > 0.8 * self.max_speed:
                speed_ratio = (self.speed - 0.8 * self.max_speed) / (0.2 * self.max_speed)
                target_current *= (1 - speed_ratio)
        
        # Apply the current
        self._set_motor_current(target_current)
        
        # Handle regenerative braking
        if (self.brake_active and 
            not self.regen_active and 
            self.battery_level < 95):
            self._activate_regen_braking(True)
        elif (not self.brake_active and self.regen_active):
            self._activate_regen_braking(False)

    def _calculate_target_current(self):
        # Base current from throttle
        throttle_current = (self.throttle_position / 100) * self.max_current
        
        # Pedal assist contribution
        if self.cadence > 10:  # If pedaling
            cadence_factor = min(self.cadence / 60, 1.5)  # Normalized to 60RPM
            
            if self.torque > 1.0:  # Significant pedaling force
                assist_current = self.torque * 2.5  # Torque gain factor
            else:
                assist_current = throttle_current * cadence_factor * 0.6
            
            # Blend throttle and pedal inputs
            target_current = max(throttle_current, assist_current)
        else:
            target_current = throttle_current
        
        # Apply assist level
        assist_multiplier = [0.7, 1.0, 1.3][self.assist_level - 1]
        target_current *= assist_multiplier
        
        # Apply PID control for smooth speed regulation
        target_speed = min(
            (self.throttle_position / 100) * self.max_speed,
            self.max_speed
        )
        
        speed_error = target_speed - self.speed
        self.pid_integral += speed_error
        derivative = speed_error - self.last_error
        self.last_error = speed_error
        
        pid_adjustment = (
            self.pid_kp * speed_error +
            self.pid_ki * self.pid_integral +
            self.pid_kd * derivative
        )
        
        return min(
            target_current * (1 + pid_adjustment),
            self.max_current
        )

    def _set_motor_current(self, current):
        self.motor_current = current
        
        if self.motor_control_type == 'PWM':
            # Convert to PWM duty cycle (0-1023)
            duty = int((current / self.max_current) * 1023)
            self.motor_pwm.duty(duty)
        else:  # UART
            cmd = bytearray(4)
            cmd[0] = 0x01  # Current command
            cmd[1] = int(current * 10)  # 0.1A resolution
            self.motor_uart.write(cmd)

    def _activate_regen_braking(self, activate):
        if activate:
            regen_current = min(5.0, self.max_current * 0.3)  # Limit to 5A or 30%
            cmd = bytearray(4)
            cmd[0] = 0x02  # Regen command
            cmd[1] = int(regen_current * 10)  # 0.1A resolution
            self.motor_uart.write(cmd)
            self.regen_active = True
        else:
            cmd = bytearray(4)
            cmd[0] = 0x02  # Regen command
            cmd[1] = 0x00  # Zero current
            self.motor_uart.write(cmd)
            self.regen_active = False

    def _check_safety_limits(self):
        if (self.motor_temp > 80 or 
            self.controller_temp > 70 or
            self.motor_current > self.max_current * 1.2 or
            self.battery_level < 5):
            
            self._emergency_shutdown()

    def _emergency_shutdown(self):
        self._set_motor_current(0)
        self.display.fill(0)
        self.display.text("EMERGENCY STOP", 0, 0)
        
        if self.motor_temp > 80:
            self.display.text("Motor Overheat", 0, 16)
        elif self.controller_temp > 70:
            self.display.text("Controller Hot", 0, 16)
        elif self.motor_current > self.max_current * 1.2:
            self.display.text("Over Current", 0, 16)
        elif self.battery_level < 5:
            self.display.text("Low Battery", 0, 16)
            
        self.display.show()

    def _update_display(self, timer):
        self.display.fill(0)
        
        # Row 1: Speed and battery
        self.display.text(f"Speed: {self.speed:.1f}km/h", 0, 0)
        self.display.text(f"Batt: {self.battery_level}%", 70, 0)
        
        # Row 2: Power and current
        self.display.text(f"Power: {self.motor_power:.0f}W", 0, 12)
        self.display.text(f"{self.motor_current:.1f}A", 90, 12)
        
        # Row 3: Distance and assist
        self.display.text(f"Dist: {self.distance:.1f}km", 0, 24)
        self.display.text(f"Mode: {self.assist_level}", 70, 24)
        
        # Row 4: Cadence and torque
        self.display.text(f"Cadence: {self.cadence}RPM", 0, 36)
        if self.torque > 0.5:
            self.display.text(f"{self.torque:.1f}Nm", 90, 36)
        
        # Row 5: Status indicators
        status = []
        if self.lights_on: status.append("LIGHTS")
        if self.horn_active: status.append("HORN")
        if self.charging: status.append("CHARGING")
        if self.regen_active: status.append("REGEN")
        self.display.text(" ".join(status), 0, 48)
        
        self.display.show()

    def set_assist_level(self, level):
        self.assist_level = max(1, min(3, level))

    def toggle_lights(self):
        self.lights_on = not self.lights_on
        self.headlight.value(self.lights_on)
        self.taillight.value(self.lights_on)

    def sound_horn(self, duration=1000):
        self.horn_active = True
        self.horn.value(1)
        Timer(-1).init(period=duration, mode=Timer.ONE_SHOT, 
                      callback=lambda t: self._horn_off())

    def _horn_off(self):
        self.horn.value(0)
        self.horn_active = False

# Main execution
if __name__ == "__main__":
    controller = EBikeController()
    
    try:
        while True:
            # Main loop can handle button inputs or other tasks
            time.sleep(0.1)
    except KeyboardInterrupt:
        controller._set_motor_current(0)
        controller.display.fill(0)
        controller.display.text("SYSTEM SHUTDOWN", 0, 0)
        controller.display.show()
