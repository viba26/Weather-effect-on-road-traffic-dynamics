
import os
import sys
import pandas as pd
import traci

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
else:
    raise EnvironmentError("SUMO_HOME environment variable is not set.")

SCENARIO_DIR = os.path.join("LuSTScenario-master", "scenario")
CONFIG_PATH = os.path.join(SCENARIO_DIR, "dua.static.sumocfg")

MAX_SIMULATION_TIME = 3600.0

WEATHER_SETTINGS = {
    "normal": {
        "tau_factor": 1.0,
        "speed_factor": 1.0,
        "accel_factor": 1.0,
        "decel_factor": 1.0
    },
    "rainy": {
        "tau_factor": 1.4,
        "speed_factor": 0.85,
        "accel_factor": 0.8,
        "decel_factor": 0.85
    },
    "snowy": {
        "tau_factor": 1.8,
        "speed_factor": 0.65,
        "accel_factor": 0.6,
        "decel_factor": 0.65
    }
}


def run_single_simulation(weather_type):
    """Run one simulation and return traffic and emission metrics."""

    if weather_type not in WEATHER_SETTINGS:
        raise ValueError(f"Unsupported weather condition: {weather_type}")

    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(
            f"SUMO configuration file not found: {CONFIG_PATH}"
        )

    settings = WEATHER_SETTINGS[weather_type]
    sumo_binary = os.environ.get("SUMO_BINARY", "sumo")

    sumo_cmd = [
        sumo_binary,
        "-c", CONFIG_PATH,
        "--no-step-log", "true",
        "--duration-log.disable", "true",
        "--end", str(MAX_SIMULATION_TIME)
    ]

    total_co2_mg = 0.0
    total_arrived = 0
    total_departed = 0
    total_speed = 0.0
    speed_samples = 0
    total_travel_time = 0.0
    completed_trips = 0
    departure_times = {}
    simulation_time = 0.0
    step = 0

    try:
        traci.start(sumo_cmd)

        step_length = traci.simulation.getDeltaT()

        if step_length <= 0:
            raise RuntimeError("Invalid simulation step length.")

        # Apply weather-related changes to existing vehicle types.
        for vtype in traci.vehicletype.getIDList():
            original_tau = traci.vehicletype.getTau(vtype)
            original_speed = traci.vehicletype.getMaxSpeed(vtype)
            original_accel = traci.vehicletype.getAccel(vtype)
            original_decel = traci.vehicletype.getDecel(vtype)

            traci.vehicletype.setTau(
                vtype,
                max(0.1, original_tau * settings["tau_factor"])
            )

            traci.vehicletype.setMaxSpeed(
                vtype,
                max(0.1, original_speed * settings["speed_factor"])
            )

            traci.vehicletype.setAccel(
                vtype,
                max(0.1, original_accel * settings["accel_factor"])
            )

            traci.vehicletype.setDecel(
                vtype,
                max(0.1, original_decel * settings["decel_factor"])
            )

        # Collect metrics at every simulation step.
        while (
            traci.simulation.getMinExpectedNumber() > 0
            and simulation_time < MAX_SIMULATION_TIME
        ):
            traci.simulationStep()
            simulation_time = traci.simulation.getTime()
            step += 1

            # Track vehicles entering the network.
            for veh_id in traci.simulation.getDepartedIDList():
                departure_times[veh_id] = simulation_time
                total_departed += 1

            # Collect vehicle-level measurements.
            vehicles = traci.vehicle.getIDList()

            for veh_id in vehicles:
                co2_rate = traci.vehicle.getCO2Emission(veh_id)

                if co2_rate >= 0:
                    total_co2_mg += co2_rate * step_length

                speed = traci.vehicle.getSpeed(veh_id)

                if speed >= 0:
                    total_speed += speed
                    speed_samples += 1

            # Count arrivals once and calculate completed trip times.
            arrived_ids = traci.simulation.getArrivedIDList()
            total_arrived += len(arrived_ids)

            for veh_id in arrived_ids:
                if veh_id in departure_times:
                    travel_time = (
                        simulation_time - departure_times.pop(veh_id)
                    )

                    if travel_time >= 0:
                        total_travel_time += travel_time
                        completed_trips += 1

    except Exception as exc:
        print(f"Simulation failed for {weather_type}: {exc}")
        return None

    finally:
        if traci.isLoaded():
            traci.close()

    average_speed_kmh = (
        total_speed / speed_samples * 3.6
        if speed_samples > 0 else 0.0
    )

    average_travel_time_s = (
        total_travel_time / completed_trips
        if completed_trips > 0 else 0.0
    )

    throughput_per_hour = (
        total_arrived / (simulation_time / 3600.0)
        if simulation_time > 0 else 0.0
    )

    return {
        "Weather": weather_type,
        "Simulation_Time_s": round(simulation_time, 2),
        "Simulation_Steps": step,
        "Departed_Vehicles": total_departed,
        "Arrived_Vehicles": total_arrived,
        "Completed_Trips": completed_trips,
        "Average_Travel_Time_s": round(average_travel_time_s, 2),
        "Average_Speed_kmh": round(average_speed_kmh, 2),
        "Traffic_Flow_veh_per_hour": round(throughput_per_hour, 2),
        "Total_CO2_g": round(total_co2_mg / 1000.0, 2)
    }


if __name__ == "__main__":
    weather_conditions = ["normal", "rainy", "snowy"]
    results = []

    for weather in weather_conditions:
        print("\n" + "=" * 50)
        print(f"Running simulation: {weather.upper()}")
        print("=" * 50)

        metrics = run_single_simulation(weather)

        if metrics is not None:
            results.append(metrics)
            print(pd.Series(metrics).to_string())

    if results:
        df = pd.DataFrame(results)

        print("\nSIMULATION RESULTS")
        print(df.to_string(index=False))

        output_path = "simulation_results.csv"
        df.to_csv(output_path, index=False)

        print(f"\nResults saved to: {output_path}")
    else:
        print("No simulation results were generated.")
