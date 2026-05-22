import bitarray as bitLib
def main():
    diccionario : dict[str, bitLib.bitarray] = { "Hola": bitLib.bitarray("00000") }
    for k, v in diccionario.items():
        print(f"{k}: {v.to01()}")
    print("Hello from chessmastercompresor3000!")



if __name__ == "__main__":
    main()
